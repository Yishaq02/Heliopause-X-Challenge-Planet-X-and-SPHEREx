import os
import sys
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

# Las pruebas no deben tropezar con el limitador ni purgar la cache real.
os.environ.setdefault("SPHEREX_RATE", "0")
os.environ.setdefault("SPHEREX_CACHE_MB", "0")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import fits_engine  # noqa: E402


def crear_fits(carpeta, n_epocas=3, tam=40):
    """FITS sintéticos: 6 detectores x n_epocas; en la última aparece un objeto."""
    carpeta.mkdir(parents=True, exist_ok=True)
    base = np.random.default_rng(0).normal(100, 1, (tam, tam)).astype("float32")
    for det in range(1, 7):
        for k in range(n_epocas):
            im = base.copy()
            if k == n_epocas - 1:
                im[10:14, 10:14] += 500
            h = fits.Header()
            h["DETECTOR"] = det
            h["MJD-OBS"] = 60000 + k
            h["WAVELEN"] = 0.75 + det * 0.5 + k * 0.01
            fits.PrimaryHDU(im, h).writeto(carpeta / f"d{det}_{k}.fits")


@pytest.fixture
def datos(tmp_path, monkeypatch):
    crear_fits(tmp_path / "barnard")
    monkeypatch.setattr(fits_engine, "DATA_DIR", tmp_path)
    fits_engine.cargar_objetivo.cache_clear()
    yield tmp_path
    fits_engine.cargar_objetivo.cache_clear()
