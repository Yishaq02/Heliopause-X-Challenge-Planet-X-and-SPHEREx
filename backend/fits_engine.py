"""Lectura de FITS locales con astropy. Un archivo = una exposicion de un detector."""
from functools import lru_cache
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.coordinates import SkyCoord
import astropy.units as u

from config import DATA_DIR


def _leer(path):
    with fits.open(path) as hdul:
        ext = "IMAGE" if "IMAGE" in hdul else next(
            i for i, h in enumerate(hdul) if h.data is not None and h.data.ndim == 2)
        hdr = hdul[ext].header.copy()
        datos = np.array(hdul[ext].data, dtype=np.float32)
    return datos, hdr


@lru_cache(maxsize=16)
def cargar_objetivo(tid):
    """Devuelve lista de epocas ordenadas por MJD."""
    carpeta = DATA_DIR / tid
    archivos = sorted(list(carpeta.glob("*.fits")) + list(carpeta.glob("*.fit")))
    if not archivos:
        raise FileNotFoundError(f"No hay FITS en {carpeta}")
    epocas = []
    for p in archivos:
        datos, hdr = _leer(p)
        epocas.append({
            "archivo": p.name,
            "mjd": float(hdr.get("MJD-OBS", 0.0)),
            "detector": int(hdr.get("DETECTOR", 1)),
            "wavelength": float(hdr.get("WAVELEN", hdr.get("LAMBDA", np.nan))),
            "imagen": datos,
            "header": hdr,
        })
    epocas.sort(key=lambda e: e["mjd"])
    return epocas


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
