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
    d = diff.diferencia(a, a)
    assert np.isnan(d).all()
    assert not diff.a_uint8(d).any()


def test_desfase_global_desaparece():
    rng = np.random.default_rng(3)
    vieja = rng.normal(100, 1, (30, 30)).astype("float32")
    nueva = vieja + 250.0   # float32 no guarda el decimal exacto
    d = diff.diferencia(nueva, vieja)
    assert np.abs(d).max() < 1e-3


def test_nan_se_propaga_y_no_se_resta():
    vieja = np.ones((10, 10), "float32")
    nueva = vieja.copy()
    nueva[2, 2] = np.nan
    d = diff.diferencia(nueva, vieja)
    assert np.isnan(d[2, 2]) and d[0, 0] == 0
    assert not diff.a_uint8(d)[2, 2]


def test_un_pixel_caliente_no_aplasta_la_imagen():
    rng = np.random.default_rng(4)
    m = rng.normal(0, 1, (100, 100)).astype("float32")
    m[50, 50] = 50.0        # fuente real
    m[0, 0] = 1e6           # pixel caliente
    assert diff.a_uint8(m)[50, 50] > 200



def test_a_uint8_rango_y_cero():
    m = np.array([[0, -5], [10, 0]], "float32")
    r = diff.a_uint8(m)
    assert r.dtype == np.uint8 and r.max() == 255 and r[0, 0] == 0
    assert not diff.a_uint8(np.zeros((4, 4))).any()


def test_base64_es_png_valido():
    m8 = np.zeros((8, 8), np.uint8)
    assert base64.b64decode(diff.a_base64(m8)).startswith(b"\x89PNG")


def _ep(mjd, wl):
    return {"mjd": mjd, "wavelength": wl, "imagen": np.zeros((4, 4))}


def test_emparejar_misma_banda():
    eps = [_ep(10, 2.00), _ep(20, 2.01), _ep(30, 3.50)]
    pares = diff.emparejar(eps, tol_um=0.02)
    assert len(pares) == 1
    assert pares[0][0]["mjd"] == 20 and pares[0][1]["mjd"] == 10


def test_emparejar_elige_la_mas_cercana():
    eps = [_ep(10, 2.000), _ep(11, 2.015), _ep(20, 2.012)]
    nueva, vieja = diff.emparejar(eps, tol_um=0.02)[-1]
    assert nueva["mjd"] == 20 and vieja["mjd"] == 11


def test_emparejar_respeta_min_dias_y_orden():
    eps = [_ep(20.0, 2.0), _ep(20.5, 2.0), _ep(10.0, 2.0)]
    pares = diff.emparejar(eps, min_dias=1.0)
    assert [(n["mjd"], v["mjd"]) for n, v in pares] == [(20.0, 10.0), (20.5, 10.0)]


def test_emparejar_sin_pares():
    assert diff.emparejar([_ep(10, 1.0), _ep(20, 3.0)]) == []
