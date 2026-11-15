import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
# Carpeta con los FITS: data/<id_objetivo>/*.fits  (ajustable)
DATA_DIR = Path(__import__("os").environ.get("FITS_DIR", BASE.parent / "data"))
FPS_VALIDOS = (5, 10)
N_DETECTORES = 6
N_CANALES = 17  # 6 x 17 = 102


def cargar_targets():
    return json.loads((BASE / "targets.json").read_text(encoding="utf-8"))


def mjd_a_anio(mjd):
    return 2000.0 + (mjd - 51544.5) / 365.25


def posicion(t, anio):
    """(ra, dec) en grados del objetivo en el anio dado (movimiento propio lineal)."""
    import math
    dt = anio - t.get("epoch", 2000.0)
    dec = t["dec"] + t.get("pmdec", 0.0) / 3.6e6 * dt
    ra = t["ra"] + t.get("pmra", 0.0) / 3.6e6 * dt / math.cos(math.radians(t["dec"]))
    return ra, dec


def get_target(tid):
    for t in cargar_targets():
        if t["id"] == tid:
            return t
    return None
