import base64

import numpy as np
import pytest

import diff


def test_estatico_da_cero():
    a = np.random.default_rng(1).normal(100, 1, (30, 30)).astype("float32")
    assert not diff.diferencia(a, a).any()


def test_detecta_cambio_y_filtra_ruido():
    rng = np.random.default_rng(2)
    vieja = rng.normal(100, 1, (30, 30)).astype("float32")
    nueva = vieja + rng.normal(0, 0.1, vieja.shape).astype("float32")
    nueva[5:8, 5:8] += 300
    d = diff.diferencia(nueva, vieja)
    assert (d[5:8, 5:8] != 0).all()
    assert (d[15:, 15:] == 0).all()


def test_signo_nueva_menos_vieja():
    vieja = np.zeros((20, 20), "float32")
    nueva = vieja.copy()
    nueva[3, 3] = 50
    assert diff.diferencia(nueva, vieja)[3, 3] > 0


def test_tamanos_distintos_se_recortan():
    d = diff.diferencia(np.zeros((30, 25)), np.zeros((20, 30)))
    assert d.shape == (20, 25)


def test_nan_no_rompe():
    a = np.full((10, 10), np.nan)
    assert np.isfinite(diff.diferencia(a, a)).all()


def test_a_uint8_rango_y_cero():
    m = np.array([[0, -5], [10, 0]], "float32")
    r = diff.a_uint8(m)
    assert r.dtype == np.uint8 and r.max() == 255 and r[0, 0] == 0
    assert not diff.a_uint8(np.zeros((4, 4))).any()


def test_base64_es_png_valido():
    m8 = np.zeros((8, 8), np.uint8)
    assert base64.b64decode(diff.a_base64(m8)).startswith(b"\x89PNG")
