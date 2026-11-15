import os
import shutil
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

import config
import cutouts
import frames as frm
import spectra
import diff as dif
import video
import gaia_check
from fits_engine import cargar_objetivo, leer_archivos

app = FastAPI(title="SPHEREx backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Limite de peticiones por IP solo en las rutas que pueden disparar descargas a IRSA.
# SPHEREX_RATE=0 lo desactiva (lo usan las pruebas).
_LIMITE_RPM = float(os.environ.get("SPHEREX_RATE", "60"))
_RAFAGA = float(os.environ.get("SPHEREX_BURST", "20"))
_RUTAS_DESCARGA = {"/cutouts", "/stack", "/spectrum", "/export-mp4"}
_VISITAS = {}
_LIM_GUARD = threading.Lock()


def _permitir(ip):
    if _LIMITE_RPM <= 0:
        return True
    ahora = time.monotonic()
    with _LIM_GUARD:
        cupo, t0 = _VISITAS.get(ip, (_RAFAGA, ahora))
        cupo = min(_RAFAGA, cupo + (ahora - t0) * _LIMITE_RPM / 60.0)
        if cupo < 1:
            _VISITAS[ip] = (cupo, ahora)
            return False
        _VISITAS[ip] = (cupo - 1, ahora)
        return True


@app.middleware("http")
async def limitar_peticiones(request, call_next):
    if request.url.path in _RUTAS_DESCARGA:
        ip = request.client.host if request.client else "sin-ip"
        if not _permitir(ip):
            return JSONResponse({"detail": "demasiadas peticiones; espera un momento"},
                                status_code=429, headers={"Retry-After": "10"})
    return await call_next(request)


@app.on_event("startup")
def _al_arrancar():
    cutouts.purgar_cache()



def _target(tid):
    t = config.get_target(tid)
    if not t:
        raise HTTPException(404, f"Objetivo desconocido: {tid}")
    return t


def _epocas(tid):
    try:
        return cargar_objetivo(tid)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


def _campo(target, ra, dec, fov, detector, maximo, pmra, pmdec):
    """Resuelve el campo pedido a (epocas, meta). target con FITS locales o coordenadas en vivo."""
    t = None
    if target:
        t = _target(target)
        try:
            return cargar_objetivo(target), {"origen": "local", "ra": t["ra"], "dec": t["dec"], "target": target}
        except FileNotFoundError:
            ra, dec = t["ra"], t["dec"]
            pmra, pmdec = t.get("pmra", 0.0), t.get("pmdec", 0.0)
    if ra is None or dec is None:
        raise HTTPException(400, "Indica target, o ra y dec")
    ep0 = t.get("epoch", 2000.0) if t else 2000.0
    # Se pide siempre el juego completo de DESCARGAS imagenes para que /cutouts y /spectrum
    # compartan cache; el submuestreo para mostrar se hace despues, en memoria.
    pedir = max(int(maximo), cutouts.DESCARGAS)
    try:
        rutas, fallos = cutouts.obtener(ra, dec, fov, detector, pedir, pmra, pmdec, ep0)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        raise HTTPException(503, f"IRSA no disponible: {e}")
    return leer_archivos(rutas), {"origen": "irsa", "ra": ra, "dec": dec, "fov": fov,
                                  "descargas_fallidas": len(fallos)}


@app.get("/cutouts")
def cutouts_ep(target: str | None = None, ra: float | None = None, dec: float | None = None,
               fov: float = 90.0, detector: int = Query(1, ge=1, le=6), mode: str = "normal",
               max: int = Query(40, ge=1, le=cutouts.MAX_EPOCAS), sigma: float = Query(3.0, gt=0),
               tol: float = Query(0.02, gt=0), min_dias: float = Query(1.0, ge=0),
               pmra: float = 0.0, pmdec: float = 0.0):
    """Frames (PNG base64) de un campo: normal, diff o stack. Coordenadas en vivo desde IRSA."""
    if mode not in ("normal", "diff", "stack"):
        raise HTTPException(400, "mode debe ser normal, diff o stack")
    eps, meta = _campo(target, ra, dec, fov, detector, max, pmra, pmdec)
    try:
        fs = frm.construir(eps, mode, detector, sigma, tol, min_dias, maximo=max)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {**meta, "mode": mode, "detector": detector, "n": len(fs), "frames": fs}


@app.get("/stack")
def stack(target: str | None = None, ra: float | None = None, dec: float | None = None,
          fov: float = 90.0, detector: int = Query(1, ge=1, le=6),
          max: int = Query(40, ge=1, le=cutouts.MAX_EPOCAS), pmra: float = 0.0, pmdec: float = 0.0):
    """Apila (media) todas las epocas de un detector para mejorar la senal sobre ruido."""
    return cutouts_ep(target, ra, dec, fov, detector, "stack", max, 3.0, 0.02, 1.0, pmra, pmdec)


@app.get("/spectrum")
def spectrum_vivo(target: str | None = None, ra: float | None = None, dec: float | None = None,
                  fov: float = 60.0, max: int = Query(120, ge=6, le=cutouts.MAX_EPOCAS),
                  pmra: float = 0.0, pmdec: float = 0.0):
    """Espectro de 102 valores para cualquier coordenada (descarga en vivo si no hay FITS locales)."""
    eps, meta = _campo(target, ra, dec, fov, None, max, pmra, pmdec)
    t = config.get_target(target) if target else None
    t = t or {"ra": ra, "dec": dec, "pmra": pmra, "pmdec": pmdec, "epoch": 2000.0}
    s = spectra.espectro_de_epocas(eps, t["ra"], t["dec"], t.get("pmra", 0.0), t.get("pmdec", 0.0),
                                   t.get("epoch", 2000.0))
    return {**meta, **s}


@app.get("/targets")
def targets():
    return config.cargar_targets()


@app.get("/spectrum/{tid}")
def spectrum(tid: str):
    t = _target(tid)
    _epocas(tid)
    return spectra.espectro(tid, t["ra"], t["dec"], t.get("pmra", 0.0), t.get("pmdec", 0.0),
                            t.get("epoch", 2000.0))


@app.get("/diff/{tid}")
def diff(tid: str, par: int = -1, detector: int = 1, sigma: float = Query(3.0, gt=0),
         tol: float = Query(0.02, gt=0), min_dias: float = Query(1.0, ge=0)):
    """Nueva - vieja para epocas del mismo detector y la misma banda (|dlambda| <= tol um).

    `par` indexa la lista de pares (orden cronologico; -1 = el mas reciente).
    """
    _target(tid)
    eps = [e for e in _epocas(tid) if e["detector"] == detector]
    pares = dif.emparejar(eps, tol, min_dias)
    if not pares:
        raise HTTPException(404, "No hay pares de la misma banda espectral con esos parametros")
    try:
        nueva, vieja = pares[par]
    except IndexError:
        raise HTTPException(400, f"par fuera de rango (hay {len(pares)})")
    m8 = dif.a_uint8(dif.diferencia(nueva["imagen"], vieja["imagen"], sigma))
    return {"shape": list(m8.shape), "png_base64": dif.a_base64(m8), "n_pares": len(pares),
            "mjd_nueva": nueva["mjd"], "mjd_vieja": vieja["mjd"],
            "wavelength_nueva": nueva["wavelength"], "wavelength_vieja": vieja["wavelength"]}


@app.get("/export-mp4")
def export_mp4(target: str | None = None, ra: float | None = None, dec: float | None = None,
               fov: float = 90.0, mode: str = "normal", fps: int = 5, detector: int = 1,
               max: int = Query(40, ge=1, le=cutouts.MAX_EPOCAS),
               tol: float = Query(0.02, gt=0), min_dias: float = Query(1.0, ge=0),
               pmra: float = 0.0, pmdec: float = 0.0):
    if mode not in ("normal", "diff"):
        raise HTTPException(400, "mode debe ser 'normal' o 'diff'")
    if fps not in config.FPS_VALIDOS:
        raise HTTPException(400, f"fps debe ser uno de {config.FPS_VALIDOS}")
    eps, meta = _campo(target, ra, dec, fov, detector, max, pmra, pmdec)
    target = target or f"{meta['ra']:.4f}_{meta['dec']:.4f}"
    try:
        ruta, tmp = video.generar_mp4_de_epocas(eps, mode, fps, detector,
                                                tol_um=tol, min_dias=min_dias, maximo=max)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Error generando MP4: {e}")
    return FileResponse(ruta, media_type="video/mp4", filename=f"{target}_{mode}.mp4",
                        background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True))


@app.get("/gaia-check")
def gaia(target: str | None = None, ra: float | None = None, dec: float | None = None,
         radius: float = 3.0):
    if target:
        t = _target(target)
        ra, dec = config.posicion(t, 2016.0)  # epoca de referencia de Gaia DR3
    if ra is None or dec is None:
        raise HTTPException(400, "Indica target o ra y dec")
    try:
        r = gaia_check.es_conocida(ra, dec, radius)
    except Exception as e:
        raise HTTPException(503, f"Gaia no disponible: {e}")
    return {**r, "anomaly": not r["known"]}


# Frontend estatico (al final para no tapar las rutas de la API)
_FRONT = Path(__file__).resolve().parent.parent / "frontend"
if _FRONT.is_dir():
    app.mount("/", StaticFiles(directory=_FRONT, html=True), name="frontend")
