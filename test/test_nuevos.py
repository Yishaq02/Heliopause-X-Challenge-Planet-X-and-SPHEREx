import sys
from pathlib import Path

import numpy as np
import pytest
from astropy.table import Table

import config
import video

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import fetchers  # noqa: E402


# --- movimiento propio -------------------------------------------------------
def test_posicion_sin_movimiento():
    t = {"ra": 10.0, "dec": 20.0}
    assert config.posicion(t, 2030.0) == (10.0, 20.0)


def test_posicion_en_la_epoca_base_no_cambia():
    t = {"ra": 269.4, "dec": 4.7, "pmra": -800, "pmdec": 10000, "epoch": 2016.0}
    assert config.posicion(t, 2016.0) == (269.4, 4.7)


def test_posicion_dec_avanza_con_pmdec():
    t = {"ra": 0.0, "dec": 0.0, "pmra": 0, "pmdec": 3600.0, "epoch": 2000.0}  # 3.6"/anio
    _, dec = config.posicion(t, 2010.0)
    assert dec == pytest.approx(0.01)  # 36" = 0.01 deg


def test_posicion_ra_se_corrige_por_cos_dec():
    t = {"ra": 0.0, "dec": 60.0, "pmra": 3600.0, "pmdec": 0, "epoch": 2000.0}  # 3.6"/anio
    ra, _ = config.posicion(t, 2001.0)
    assert ra == pytest.approx(0.002)  # 3.6"/cos(60) = 7.2" = 0.002 deg


def test_barnard_se_mueve_al_norte():
    t = config.get_target("barnard")
    _, d0 = config.posicion(t, 2016.0)
    _, d1 = config.posicion(t, 2026.0)
    assert d1 - d0 == pytest.approx(10362.4 / 3.6e6 * 10, rel=1e-6)


def test_mjd_a_anio():
    assert config.mjd_a_anio(51544.5) == pytest.approx(2000.0)


def test_los_5_objetivos_tienen_coordenadas():
    ts = config.cargar_targets()
    assert len(ts) == 5
    assert all(not (t["ra"] == 0 and t["dec"] == 0) for t in ts)
    assert {"barnard", "epsilon_indi_b", "wise0855", "rw_aur", "r_dra"} == {t["id"] for t in ts}


# --- escalado de video -------------------------------------------------------
def test_escalar_agranda_sin_suavizar():
    f = np.arange(16, dtype=np.uint8).reshape(4, 4)
    g = video.escalar(f, lado_min=8)
    assert g.shape == (8, 8) and set(np.unique(g)) == set(np.unique(f))


def test_escalar_no_toca_imagenes_grandes():
    f = np.zeros((600, 700), np.uint8)
    assert video.escalar(f) is f


def test_escalar_dimensiones_pares():
    g = video.escalar(np.zeros((15, 15), np.uint8))
    assert g.shape[0] % 2 == 0 and min(g.shape) >= 480


# --- combinar colecciones ----------------------------------------------------
def _tabla(urls):
    return Table({"access_url": urls, "t_min": [1.0] * len(urls)})


def test_spherex_todas_combina_y_quita_duplicados(monkeypatch):
    datos = {"spherex_dr1": _tabla(["a", "b"]), "spherex_qr3": _tabla(["b", "c"])}
    monkeypatch.setattr(fetchers.Irsa, "query_sia", lambda pos, collection: datos[collection])
    tabla, col = fetchers.spherex_todas(None, 10)
    assert sorted(tabla["access_url"]) == ["a", "b", "c"]
    assert col == "spherex_dr1+spherex_qr3"


def test_spherex_todas_falla_si_una_coleccion_cae(monkeypatch):
    def q(pos, collection):
        if collection == "spherex_dr1":
            raise ConnectionError("502")
        return _tabla(["x"])
    monkeypatch.setattr(fetchers.Irsa, "query_sia", q)
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="spherex_dr1"):
        fetchers.spherex_todas(None, 10)


def test_spherex_todas_sin_resultados(monkeypatch):
    monkeypatch.setattr(fetchers.Irsa, "query_sia", lambda pos, collection: _tabla([]))
    assert fetchers.spherex_todas(None, 10) == (None, None)
