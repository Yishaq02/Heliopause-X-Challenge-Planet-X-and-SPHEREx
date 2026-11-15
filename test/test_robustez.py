import threading

import numpy as np
import pytest
from astropy.io import fits
from astropy.table import Table
from fastapi.testclient import TestClient

import app
import cutouts
import fits_engine
import frames as frm


def _tabla(n=12):
    return Table({"access_url": [f"http://x/1/f{i}.fits" for i in range(n)],
                  "t_min": [60000.0 + i for i in range(n)]})


# --- cache y descargas -------------------------------------------------------
def test_carpeta_incluye_movimiento_propio():
    a = cutouts.carpeta_de(10, 20, 90)
    b = cutouts.carpeta_de(10, 20, 90, pmra=1000, pmdec=-500, epoch=2016.0)
    assert a != b and "pm1000.00" in b.name


def test_consultar_radio_crece_con_el_campo(monkeypatch):
    vistos = []

    def f(coord, radio=10):
        vistos.append(radio)
        return None, None
    monkeypatch.setattr(cutouts.fetchers, "spherex_todas", f)
    cutouts.consultar(10, 20, fov=90)
    cutouts.consultar(10, 20, fov=300)
    assert vistos == [55.0, 160.0]


def test_obtener_concurrente_descarga_una_vez(tmp_path, monkeypatch):
    monkeypatch.setattr(cutouts, "consultar", lambda ra, dec, **k: _tabla())
    creados = []

    def lento(fila, pos_fn, fov, out, reintentos=3):
        if out.exists():
            return "ya existe"
        creados.append(out.name)
        out.write_bytes(_fits(mjd=float(fila["t_min"])))
        return "ok"
    monkeypatch.setattr(cutouts, "bajar_recorte", lento)
    salidas = []

    def worker():
        salidas.append(cutouts.obtener(10, 20, 60, maximo=6, carpeta=tmp_path))
    hilos = [threading.Thread(target=worker) for _ in range(3)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert sorted(creados) == sorted(set(creados)) and len(creados) == 6
    assert not list(tmp_path.glob("*.part"))
    assert (tmp_path / "_meta.json").exists()


def _fits(mjd=60000.0, det=1):
    img = np.ones((15, 15), np.float32)
    h = fits.Header()
    h["DETECTOR"], h["MJD-OBS"] = det, mjd
    h["WAVELEN"] = 1.0 + (mjd - 60000.0) / 100.0
    import io
    b = io.BytesIO()
    fits.HDUList([fits.PrimaryHDU(img, h)]).writeto(b)
    return b.getvalue()


# --- cache de objetivos locales ---------------------------------------------
def test_cargar_objetivo_se_refresca_al_agregar_un_fits(datos):
    antes = len(fits_engine.cargar_objetivo("barnard"))
    (datos / "barnard" / "nuevo.fits").write_bytes(_fits(mjd=70000.0, det=1))
    assert len(fits_engine.cargar_objetivo("barnard")) == antes + 1


# --- apilado con NaN ---------------------------------------------------------
def test_media_sin_nan_no_cuenta_huecos():
    a = np.ones((4, 4), np.float32)
    a[0, 0] = np.nan
    b = np.full((4, 4), 3.0, np.float32)
    m = frm._media_sin_nan([a, b])
    assert m[0, 0] == 3.0 and m[1, 1] == 2.0


def test_frames_stack_reporta_rango_de_lambda():
    eps = [{"mjd": 10, "wavelength": 2.0, "detector": 1, "imagen": np.ones((4, 4)), "flags": None},
           {"mjd": 20, "wavelength": 3.0, "detector": 1, "imagen": np.ones((4, 4)), "flags": None}]
    f = frm.construir(eps, "stack")[0]
    assert (f["wavelength_min"], f["wavelength_max"]) == (2.0, 3.0)


def test_frames_submuestrea_normal_y_diff():
    eps = [{"mjd": i, "wavelength": 2.0, "detector": 1,
            "imagen": np.full((4, 4), float(i)), "flags": None} for i in range(20)]
    assert len(frm.construir(eps, "normal", maximo=5)) == 5
    assert len(frm.construir(eps, "diff", maximo=4)) == 4


# --- cache compartida entre imagenes y espectro ------------------------------
def test_cutouts_y_spectrum_comparten_cache(tmp_path, monkeypatch, cliente):
    monkeypatch.setattr(cutouts, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(cutouts, "DESCARGAS", 8)
    monkeypatch.setattr(cutouts, "consultar", lambda ra, dec, **k: _tabla(8))
    creados = []

    def crear(fila, pos_fn, fov, out, reintentos=3):
        if out.exists():
            return "ya existe"
        creados.append(out.name)
        out.write_bytes(_fits(mjd=float(fila["t_min"])))
        return "ok"
    monkeypatch.setattr(cutouts, "bajar_recorte", crear)
    r1 = cliente.get("/cutouts?ra=10&dec=20&fov=90&max=3").json()
    r2 = cliente.get("/spectrum?ra=10&dec=20&fov=90&max=8").json()
    assert r1["n"] == 3 and len(r2["flux"]) == 102
    assert len(creados) == 8 and len(set(creados)) == 8


# --- limitador ---------------------------------------------------------------
@pytest.fixture
def cliente(datos):
    return TestClient(app.app)


def test_limitador_devuelve_429(cliente, monkeypatch):
    monkeypatch.setattr(app, "_LIMITE_RPM", 1.0)
    monkeypatch.setattr(app, "_RAFAGA", 1.0)
    app._VISITAS.clear()
    assert cliente.get("/cutouts?target=barnard&max=1").status_code == 200
    assert cliente.get("/cutouts?target=barnard&max=1").status_code == 429
    app._VISITAS.clear()
