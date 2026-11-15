import numpy as np
import pytest

import fits_engine
import spectra


def test_cargar_ordena_por_mjd(datos):
    ep = fits_engine.cargar_objetivo("barnard")
    assert len(ep) == 18
    mjds = [e["mjd"] for e in ep]
    assert mjds == sorted(mjds)
    assert {e["detector"] for e in ep} == set(range(1, 7))


def test_carpeta_inexistente(datos):
    with pytest.raises(FileNotFoundError):
        fits_engine.cargar_objetivo("nada")


def test_flujo_en_centro_sin_wcs(datos):
    e = fits_engine.cargar_objetivo("barnard")[0]
    assert abs(fits_engine.flujo_en(e, 0, 0) - 100) < 5


def test_flujo_fuera_de_imagen_es_nan():
    e = {"imagen": np.ones((5, 5)), "header": {}}
    # sin WCS cae al centro, que sí es válido
    assert fits_engine.flujo_en(e, 0, 0) == 1.0


def test_espectro_102_valores(datos):
    s = spectra.espectro("barnard", 269.4521, 4.6934)
    assert len(s["flux"]) == 102 and len(s["wavelengths"]) == 102
    assert all(v is not None for v in s["flux"])


def test_espectro_ordenado_por_detector(datos):
    w = spectra.espectro("barnard", 0, 0)["wavelengths"]
    for d in range(6):
        tramo = w[d * 17:(d + 1) * 17]
        assert tramo == sorted(tramo)


def test_canales_vacio_da_nan():
    wl, fl = spectra._canales([], [])
    assert len(wl) == 17 and np.isnan(fl).all()
