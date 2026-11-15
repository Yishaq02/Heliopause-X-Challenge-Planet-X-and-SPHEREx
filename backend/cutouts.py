"""Recortes de SPHEREx en vivo desde IRSA, con cache en disco.

Cada archivo guardado es una imagen pequena (IMAGE + FLAGS) con DETECTOR, MJD-OBS y WAVELEN (um).

Optimizacion importante: un recorte completo pesa ~4 MB, casi todo la extension EPSF (441 zonas
de PSF) y la tabla WCS-WAVE al final. Solo hacen falta IMAGE y FLAGS (~50 KB). Se lee el cuerpo
por partes y se corta la conexion tras FLAGS. La longitud de onda se calcula con la tabla WCS-WAVE
de cada detector, que es identica para todas las visitas de una misma version (comprobado), y se
guarda una vez en data/_wcs/.
"""
import io
import json
import os
import shutil
import threading
import time
import uuid
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests
from astropy import log as astropy_log
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS

import fetchers
from config import DATA_DIR, posicion

CACHE_DIR = DATA_DIR / "_cache"
WCS_DIR = DATA_DIR / "_wcs"
FOV_MIN, FOV_MAX = 30.0, 300.0
MAX_EPOCAS = 150
# Siempre se baja este numero de imagenes (repartidas en el tiempo) por campo. Asi la vista
# de imagenes y el espectro comparten la misma descarga y una segunda visita sale de cache.
DESCARGAS = 120
# Peticiones simultaneas a IRSA. Subirlo acelera el primer llenado pero multiplica los 503.
_DESCARGAS_SIMULTANEAS = max(1, int(os.environ.get("SPHEREX_CONCURRENCIA", "6")))
_MAX_CABECERA = 100 * 2880

warnings.filterwarnings("ignore", module="astropy")
astropy_log.setLevel("WARNING")  # silencia el INFO repetido sobre SIP en las cabeceras de SPHEREx

_SEMAFORO = threading.Semaphore(_DESCARGAS_SIMULTANEAS)
_LOCKS = {}
_MAP_LOCKS = {}
_LOCKS_GUARD = threading.Lock()
_MAPAS = {}


def validar(ra, dec, fov):
    if not (0.0 <= ra < 360.0):
        raise ValueError("ra debe estar en [0, 360)")
    if not (-90.0 <= dec <= 90.0):
        raise ValueError("dec debe estar en [-90, 90]")
    if not (FOV_MIN <= fov <= FOV_MAX):
        raise ValueError(f"fov debe estar entre {FOV_MIN:.0f} y {FOV_MAX:.0f} arcsec")


def nombre(fila):
    return Path(str(fila["access_url"]).split("?")[0]).name


def detector_de(fila):
    """El detector (1-6) es el directorio que precede al nombre del archivo en la URL de IRSA."""
    try:
        return int(str(fila["access_url"]).split("?")[0].split("/")[-2])
    except (ValueError, IndexError):
        return None


def seleccionar(tabla, detector=None, maximo=60):
    """Filas ordenadas por fecha, filtradas por detector y espaciadas uniformemente en el tiempo."""
    filas = sorted(tabla, key=lambda f: float(f["t_min"]))
    if detector is not None:
        filas = [f for f in filas if detector_de(f) == detector]
    if len(filas) > maximo:
        idx = np.unique(np.linspace(0, len(filas) - 1, maximo).round().astype(int))
        filas = [filas[i] for i in idx]
    return filas


def carpeta_de(ra, dec, fov, pmra=0.0, pmdec=0.0, epoch=2000.0):
    """Cache separada por posicion, tamano y movimiento propio (centrar depende de pm y epoch)."""
    return CACHE_DIR / (f"{ra:.5f}_{dec:.5f}_{fov:.0f}"
                        f"_pm{pmra:.2f}_{pmdec:.2f}_e{epoch:.1f}")


def _lock(carpeta):
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(str(carpeta), threading.Lock())


def _lock_mapa(det, ver):
    with _LOCKS_GUARD:
        return _MAP_LOCKS.setdefault((int(det), str(ver)), threading.Lock())


def _espera(resp, intento):
    """Segundos a esperar: cabecera Retry-After o backoff exponencial 1, 2, 4..."""
    try:
        return max(0.0, float(resp.headers.get("Retry-After")))
    except (AttributeError, TypeError, ValueError):
        return float(2 ** intento)


# --- lectura incremental de FITS ------------------------------------------------
def _leer_exacto(fuente, n):
    """Lee exactamente n bytes de un stream (resp.raw.read puede devolver menos)."""
    partes, resto = [], n
    while resto > 0:
        trozo = fuente.read(min(resto, 65536))
        if not trozo:
            raise EOFError("recorte truncado")
        partes.append(trozo)
        resto -= len(trozo)
    return b"".join(partes)


def _parsear_cabecera(datos):
    h = {}
    for i in range(0, len(datos) - 79, 80):
        tarjeta = datos[i:i + 80]
        clave = tarjeta[:8].decode("ascii", "replace").strip()
        if not clave or clave in ("COMMENT", "HISTORY") or tarjeta[8:10] != b"= ":
            continue
        bruto = tarjeta[10:].decode("ascii", "replace").strip()
        if bruto.startswith("'"):
            fin = bruto.find("'", 1)
            valor = bruto[1:fin] if fin > 0 else bruto.strip("'")
        else:
            valor = bruto.split("/")[0]
        h[clave] = valor.strip()  # VERSION llega como '7.0.5   ' y debe coincidir con astropy
    return h


def _leer_cabecera(fuente, buf):
    cab = bytearray()
    while True:
        cab += _leer_exacto(fuente, 2880)
        if any(cab[i:i + 8].strip() == b"END" for i in range(0, len(cab), 80)):
            break
        if len(cab) > _MAX_CABECERA:
            raise ValueError("cabecera FITS demasiado larga")
    buf += cab
    return _parsear_cabecera(bytes(cab))


def _bytes_datos(h):
    naxis = int(h.get("NAXIS", 0) or 0)
    bitpix = abs(int(h.get("BITPIX", 8) or 8))
    prod = 0 if naxis == 0 else 1
    for i in range(1, naxis + 1):
        prod *= int(h.get(f"NAXIS{i}", 0) or 0)
    n = bitpix // 8 * int(h.get("GCOUNT", 1) or 1) * (int(h.get("PCOUNT", 0) or 0) + prod)
    return n + (-n) % 2880


def _leer_hasta(fuente, det):
    """Bytes FITS con IMAGE y FLAGS (y WCS-WAVE si aun no hay tabla del detector).

    Si falta la tabla de un detector, un unico hilo la descarga y la guarda mientras los demas
    esperan a ese cerrojo; asi no se bajan varios EPSF de 4 MB en paralelo al arrancar.
    """
    buf = bytearray()
    principal = _leer_cabecera(fuente, buf)
    buf += _leer_exacto(fuente, _bytes_datos(principal))
    ver = principal.get("VERSION", "x")
    nombres, cerrojo, bootstrap = set(), None, False
    try:
        for _ in range(10):
            h = _leer_cabecera(fuente, buf)
            ext = (h.get("EXTNAME") or "").strip().upper()
            if ext == "IMAGE" and det is None:
                det = int(h.get("DETECTOR", 1) or 1)
            if ext == "IMAGE" and det is not None and cerrojo is None:
                if _cargar_mapa(det, ver) is None:
                    cerrojo = _lock_mapa(det, ver)
                    cerrojo.acquire()
                    if _cargar_mapa(det, ver) is None:
                        bootstrap = True  # este hilo baja la tabla y despierta a los demas
                    else:
                        cerrojo.release()
                        cerrojo = None
            necesarios = {"IMAGE", "FLAGS"}
            if _cargar_mapa(det, ver) is None:
                necesarios.add("WCS-WAVE")
            if ext in necesarios:
                nombres.add(ext)
            buf += _leer_exacto(fuente, _bytes_datos(h))
            if ext == "WCS-WAVE" and bootstrap:
                try:
                    with fits.open(io.BytesIO(bytes(buf))) as hl:
                        _guardar_mapa(det, ver, _tabla_de(hl["WCS-WAVE"]))
                except Exception:
                    pass
            if necesarios <= nombres:
                break
    finally:
        if cerrojo is not None:
            cerrojo.release()
    return bytes(buf)


# --- tabla de longitud de onda por detector ------------------------------------
def _ruta_mapa(det, ver):
    seguro = str(ver).replace("/", "_").replace("\\", "_")
    return WCS_DIR / f"{int(det)}_{seguro}.json"


def _cargar_mapa(det, ver):
    if det is None:
        return None
    clave = (int(det), str(ver))
    if clave in _MAPAS:
        return _MAPAS[clave]
    ruta = _ruta_mapa(det, ver)
    if not ruta.exists():
        return None
    try:
        mapa = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    _MAPAS[clave] = mapa
    return mapa


def _tabla_de(hdu):
    d = hdu.data
    return {"x": [int(v) for v in d["X"][0]],
            "y": [int(v) for v in d["Y"][0]],
            "values": np.array(d["VALUES"][0], dtype=float).tolist()}


def _guardar_mapa(det, ver, tabla):
    if det is None:
        return
    try:
        WCS_DIR.mkdir(parents=True, exist_ok=True)
        ruta = _ruta_mapa(det, ver)
        tmp = ruta.with_name(f".{ruta.name}.{uuid.uuid4().hex[:6]}.part")
        tmp.write_text(json.dumps(tabla), encoding="utf-8")
        tmp.replace(ruta)
    except OSError:
        return
    _MAPAS[(int(det), str(ver))] = tabla


def _hdu_wave(tabla):
    x = np.asarray(tabla["x"], dtype=int)
    y = np.asarray(tabla["y"], dtype=int)
    vals = np.asarray(tabla["values"], dtype=float, order="C")
    # TDIM se escribe en orden inverso al de la forma en memoria: para leer (9,9,2) hay que
    # pasar dim=(2,9,9). VALUES se guarda tal como se leyó del archivo original (9,9,2).
    dim = "(" + ",".join(str(s) for s in reversed(vals.shape)) + ")"
    return fits.BinTableHDU.from_columns([
        fits.Column(name="X", format=f"{len(x)}J", array=[x]),
        fits.Column(name="Y", format=f"{len(y)}J", array=[y]),
        fits.Column(name="VALUES", format=f"{vals.size}E", array=[vals.ravel()], dim=dim),
    ], name="WCS-WAVE")


def _de_bytes(datos, det):
    """(imagen, header con WAVELEN, flags) desde un FITS ya descargado (parcial o completo)."""
    with fits.open(io.BytesIO(datos)) as h:
        if "IMAGE" not in h:
            raise ValueError("el recorte no tiene extension IMAGE")
        ver = h[0].header.get("VERSION", "x")
        hdr = h["IMAGE"].header.copy()
        if det is None:
            det = int(hdr.get("DETECTOR", 1) or 1)
        imagen = np.array(h["IMAGE"].data, dtype=np.float32)
        flags = np.array(h["FLAGS"].data) if "FLAGS" in h else None
        if "WCS-WAVE" in h:
            tabla = _tabla_de(h["WCS-WAVE"])
            if _cargar_mapa(det, ver) is None:
                _guardar_mapa(det, ver, tabla)
        else:
            tabla = _cargar_mapa(det, ver)

    wl = np.nan
    if tabla is not None:
        hdus = [fits.PrimaryHDU(), fits.ImageHDU(imagen, hdr, name="IMAGE")]
        if flags is not None:
            hdus.append(fits.ImageHDU(flags, name="FLAGS"))
        hdus.append(_hdu_wave(tabla))
        try:
            ny, nx = imagen.shape
            wl = float(WCS(hdr, fits.HDUList(hdus), key="W")
                       .pixel_to_world_values((nx - 1) / 2, (ny - 1) / 2)[0])
        except Exception:
            wl = np.nan

    for k in [k for k, v in hdr.items() if isinstance(v, float) and v != v]:
        del hdr[k]  # FITS no admite NaN en headers
    if np.isfinite(wl):
        hdr["WAVELEN"] = (wl, "um, longitud de onda en el centro del recorte")
    return imagen, hdr, flags


def _descargar(url, det):
    """Intenta el corte temprano; si no es posible, baja el archivo completo."""
    resp = requests.get(url, timeout=120, stream=True)
    try:
        resp.raise_for_status()
        if getattr(resp, "raw", None) is None:
            return _de_bytes(resp.content, det)
        try:
            return _de_bytes(_leer_hasta(resp.raw, det), det)
        except (EOFError, ValueError, OSError):
            pass  # stream no parseable: se reintenta completo abajo
    finally:
        try:
            resp.close()
        except Exception:
            pass
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    return _de_bytes(resp.content, det)


# --- descarga de un recorte -----------------------------------------------------
def bajar_recorte(fila, pos_fn, fov_arcsec, out, reintentos=3):
    """Descarga un recorte; escritura atomica. Devuelve 'ok'/'ya existe'/'fallo: ...'.

    pos_fn(anio) -> (ra, dec): permite centrar en la posicion del objeto en la fecha de la observacion.
    """
    if out.exists():
        return "ya existe"
    ra, dec = pos_fn(2000.0 + (float(fila["t_min"]) - 51544.5) / 365.25)
    url = f"{fila['access_url']}?center={ra},{dec}deg&size={fov_arcsec / 3600}deg"
    tmp = out.with_name(f"{out.name}.{uuid.uuid4().hex[:8]}.part")
    err = None
    resp = None
    for intento in range(reintentos):
        try:
            with _SEMAFORO:
                imagen, hdr, flags = _descargar(url, detector_de(fila))
            hdus = [fits.PrimaryHDU(imagen, hdr)]
            if flags is not None:
                hdus.append(fits.ImageHDU(flags, name="FLAGS"))
            fits.HDUList(hdus).writeto(tmp, overwrite=True, output_verify="silentfix")
            tmp.replace(out)
            return "ok"
        except Exception as e:
            err = e
            tmp.unlink(missing_ok=True)
            if intento + 1 < reintentos:
                time.sleep(_espera(resp, intento))
    return f"fallo: {err}"


def consultar(ra, dec, fov=90.0, reintentos=6, espera=15):
    """Tabla SIA combinada DR1+QR3. RuntimeError si IRSA no responde; None si no hay datos.

    El radio de busqueda crece con el campo: una observacion cuyo centro esta a media
    diagonal de distancia igual cubre la zona pedida.
    """
    coord = SkyCoord(ra, dec, unit="deg")
    radio = max(30.0, fov / 2.0 + 10.0)
    ultimo = None
    for _ in range(reintentos):
        try:
            tabla, _col = fetchers.spherex_todas(coord, radio=radio)
            return tabla
        except RuntimeError as e:
            ultimo = e
            time.sleep(espera)
    raise RuntimeError(f"IRSA no respondio: {ultimo}")


def _escribir_meta(carpeta, datos):
    try:
        tmp = carpeta / f"._meta.{uuid.uuid4().hex[:8]}.part"
        tmp.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        tmp.replace(carpeta / "_meta.json")
    except OSError:
        pass


def obtener(ra, dec, fov=90.0, detector=None, maximo=60, pmra=0.0, pmdec=0.0, epoch=2000.0,
            carpeta=None, reintentos_consulta=6):
    """Devuelve (rutas FITS cacheadas, fallos) del campo pedido, ordenadas por fecha.

    Lanza ValueError (parametros), RuntimeError (IRSA caido) o LookupError (sin datos).
    Dos peticiones simultaneas del mismo campo comparten la descarga (lock por carpeta).
    """
    validar(ra, dec, fov)
    maximo = max(1, min(int(maximo), MAX_EPOCAS))
    t = {"ra": ra, "dec": dec, "pmra": pmra, "pmdec": pmdec, "epoch": epoch}
    pos_fn = lambda anio: posicion(t, anio)  # noqa: E731
    if carpeta is None:
        carpeta = carpeta_de(ra, dec, fov, pmra, pmdec, epoch)
    carpeta.mkdir(parents=True, exist_ok=True)

    with _lock(carpeta):
        tabla = consultar(*pos_fn(2025.9), fov=fov, reintentos=reintentos_consulta)
        if tabla is None or len(tabla) == 0:
            raise LookupError("SPHEREx no tiene observaciones de ese campo")
        filas = seleccionar(tabla, detector, maximo)
        if not filas:
            raise LookupError("No hay observaciones de ese detector en el campo")

        with ThreadPoolExecutor(_DESCARGAS_SIMULTANEAS) as ex:
            res = list(ex.map(lambda f: bajar_recorte(f, pos_fn, fov, carpeta / nombre(f)), filas))
        rutas = [carpeta / nombre(f) for f, r in zip(filas, res) if (carpeta / nombre(f)).exists()]
        if not rutas:
            raise RuntimeError("No se pudo descargar ningun recorte (IRSA con errores)")
        _escribir_meta(carpeta, {"ra": ra, "dec": dec, "fov": fov, "pmra": pmra, "pmdec": pmdec,
                                 "epoch": epoch, "detector": detector, "maximo": maximo,
                                 "archivos": len(rutas),
                                 "fallos": sum(1 for r in res if r.startswith("fallo"))})
    return rutas, [r for r in res if r.startswith("fallo")]


def purgar_cache(limite_mb=None):
    """Borra las carpetas mas antiguas si la cache supera `limite_mb` (env SPHEREX_CACHE_MB)."""
    if limite_mb is None:
        limite_mb = int(os.environ.get("SPHEREX_CACHE_MB", "2048"))
    if limite_mb <= 0 or not CACHE_DIR.is_dir():
        return 0
    carpetas = []
    for p in CACHE_DIR.iterdir():
        if p.is_dir():
            tam = sum(f.stat().st_size for f in p.glob("*") if f.is_file())
            carpetas.append((p.stat().st_mtime, p, tam))
    total = sum(c[2] for c in carpetas)
    borradas = 0
    for _mtime, p, tam in sorted(carpetas):
        if total <= limite_mb * 1024 * 1024:
            break
        shutil.rmtree(p, ignore_errors=True)
        total -= tam
        borradas += 1
    return borradas
