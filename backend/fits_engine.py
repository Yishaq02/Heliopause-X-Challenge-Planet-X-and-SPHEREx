"""Lectura de FITS locales con astropy. Un archivo = una exposicion de un detector."""
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.coordinates import SkyCoord
import astropy.units as u

from config import DATA_DIR

# tid -> (firma de los archivos, epocas). La firma evita servir datos viejos si se
# descargan FITS nuevos con el servidor en marcha.
_CACHE = {}


def _leer(path):
    """Devuelve (imagen, header, flags|None)."""
    with fits.open(path) as hdul:
        ext = "IMAGE" if "IMAGE" in hdul else next(
            i for i, h in enumerate(hdul) if h.data is not None and h.data.ndim == 2)
        hdr = hdul[ext].header.copy()
        datos = np.array(hdul[ext].data, dtype=np.float32)
        flags = np.array(hdul["FLAGS"].data) if "FLAGS" in hdul else None
    return datos, hdr, flags


def leer_archivos(archivos):
    """Lista de epocas (dict) ordenadas por MJD a partir de rutas FITS."""
    epocas = []
    for p in archivos:
        datos, hdr, flags = _leer(p)
        epocas.append({
            "archivo": p.name,
            "mjd": float(hdr.get("MJD-OBS", 0.0)),
            "detector": int(hdr.get("DETECTOR", 1)),
            "wavelength": float(hdr.get("WAVELEN", hdr.get("LAMBDA", np.nan))),
            "imagen": datos,
            "flags": flags,
            "header": hdr,
        })
    epocas.sort(key=lambda e: e["mjd"])
    return epocas


def _firma(archivos):
    st = [p.stat() for p in archivos]
    return len(archivos), max(s.st_mtime for s in st), sum(s.st_size for s in st)


def cargar_objetivo(tid):
    """Devuelve lista de epocas ordenadas por MJD (se refresca si cambian los archivos)."""
    carpeta = DATA_DIR / tid
    archivos = sorted(list(carpeta.glob("*.fits")) + list(carpeta.glob("*.fit")))
    if not archivos:
        raise FileNotFoundError(f"No hay FITS en {carpeta}")
    firma = _firma(archivos)
    guardado = _CACHE.get(tid)
    if guardado and guardado[0] == firma:
        return guardado[1]
    epocas = leer_archivos(archivos)
    _CACHE[tid] = (firma, epocas)
    return epocas


def cache_clear():
    _CACHE.clear()


cargar_objetivo.cache_clear = cache_clear


def submuestrear(epocas, maximo=None):
    """Hasta `maximo` elementos, repartidos uniformemente en el orden recibido."""
    epocas = list(epocas)
    if not maximo or len(epocas) <= maximo:
        return epocas
    idx = np.unique(np.linspace(0, len(epocas) - 1, int(maximo)).round().astype(int))
    return [epocas[i] for i in idx]


def flujo_en(epoca, ra, dec, medio_lado=1):
    """Media del flujo en una ventana alrededor de (ra, dec) usando el WCS."""
    img = epoca["imagen"]
    try:
        x, y = WCS(epoca["header"]).celestial.world_to_pixel(
            SkyCoord(ra * u.deg, dec * u.deg))
        x, y = int(round(float(x))), int(round(float(y)))
    except Exception:
        y, x = img.shape[0] // 2, img.shape[1] // 2
    if not (0 <= y < img.shape[0] and 0 <= x < img.shape[1]):
        return float("nan")
    v = img[max(0, y - medio_lado):y + medio_lado + 1, max(0, x - medio_lado):x + medio_lado + 1]
    return float(np.nanmean(v)) if np.isfinite(v).any() else float("nan")
