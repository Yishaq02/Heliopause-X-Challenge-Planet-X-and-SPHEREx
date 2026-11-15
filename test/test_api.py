import base64
import shutil

import numpy as np
import pytest
from astropy.io import fits
from fastapi.testclient import TestClient

import app
import fits_engine
import gaia_check
import video


@pytest.fixture
def cliente(datos):
    return TestClient(app.app)


def test_targets(cliente):
    r = cliente.get("/targets").json()
    assert len(r) == 5 and r[0]["id"] == "barnard"


def test_spectrum(cliente):
    assert len(cliente.get("/spectrum/barnard").json()["flux"]) == 102


def test_spectrum_404(cliente):
    assert cliente.get("/spectrum/nope").status_code == 404
    # objetivo válido sin FITS
    assert cliente.get("/spectrum/objetivo3").status_code == 404


def test_fits_index(cliente):
    r = cliente.get("/fits/barnard").json()
    assert r["count"] == 18
    assert r["epochs"][0]["png_url"] == "/fits/barnard/0?format=png"


def test_fits_original(cliente):
    r = cliente.get("/fits/barnard/0")
    assert r.status_code == 200 and r.headers["content-type"] == "image/fits"
    assert r.content.startswith(b"SIMPLE")


def test_fits_png(cliente):
    r = cliente.get("/fits/barnard/7?format=png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG")


def test_fits_validacion(cliente):
    assert cliente.get("/fits/barnard/999").status_code == 400
    assert cliente.get("/fits/barnard/0?format=jpg").status_code == 422


def test_diff(cliente):
    r = cliente.get("/diff/barnard").json()
    assert r["shape"] == [40, 40]
    assert base64.b64decode(r["png_base64"]).startswith(b"\x89PNG")
    assert r["mjd_nueva"] > r["mjd_vieja"]


def test_diff_indice_invalido(cliente):
    assert cliente.get("/diff/barnard?a=999").status_code == 400
    assert cliente.get("/diff/barnard?sigma=0").status_code == 422


@pytest.mark.parametrize("q", ["fps=7", "mode=raro"])
def test_export_validacion(cliente, q):
    assert cliente.get(f"/export-mp4?target=barnard&{q}").status_code == 400


def test_export_sin_ffmpeg(cliente, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _: None)
    assert cliente.get("/export-mp4?target=barnard").status_code == 500


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg no instalado")
@pytest.mark.parametrize("modo", ["normal", "diff"])
def test_export_mp4_real(cliente, modo):
    r = cliente.get(f"/export-mp4?target=barnard&mode={modo}&fps=10")
    assert r.status_code == 200 and r.headers["content-type"] == "video/mp4"
    assert len(r.content) > 0


def test_frames_cantidad(datos):
    assert len(video.frames("barnard", "normal")) == 3
    assert len(video.frames("barnard", "diff")) == 2


def test_diff_detector_sin_datos(cliente):
    assert cliente.get("/diff/barnard?detector=9").status_code == 400


def test_diff_otro_detector(cliente):
    assert cliente.get("/diff/barnard?detector=3").json()["png_base64"]


def test_gaia_requiere_parametros(cliente):
    assert cliente.get("/gaia-check").status_code == 400


def test_gaia_mock(cliente, monkeypatch):
    monkeypatch.setattr(
        gaia_check,
        "es_conocida",
        lambda ra, dec, r: {"known": False, "n": 0, "nearest_arcsec": None},
    )
    r = cliente.get("/gaia-check?target=barnard").json()
    assert r["known"] is False and r["anomaly"] is True


def test_gaia_caida_da_503(cliente, monkeypatch):
    def falla(*a):
        raise ConnectionError("sin red")

    monkeypatch.setattr(gaia_check, "es_conocida", falla)
    assert cliente.get("/gaia-check?ra=1&dec=2").status_code == 503


def test_detector_banda():
    assert app.spherex_real_loader._detector("SPHEREx-D6") == 6
    assert app.spherex_real_loader._detector("sin-banda") == 1


def test_descargar_a_disco(tmp_path, monkeypatch):
    recorte = {"imagen": np.ones((4, 4), "float32"), "mjd": 60000.5,
               "wavelength": 4.5, "detector": 6, "header": fits.Header()}
    loader = app.spherex_real_loader
    monkeypatch.setattr(loader, "obtener_recortes_reales_spherex",
                        lambda *a, **k: ([recorte], "ok"))
    n, _ = loader.descargar_a_disco("1deg", "2deg", tmp_path)
    h = fits.open(next(tmp_path.glob("*.fits")))[0].header
    assert n == 1 and (h["DETECTOR"], h["MJD-OBS"], h["WAVELEN"]) == (6, 60000.5, 4.5)


def test_spectrum_sin_fits_da_503(tmp_path, monkeypatch):
    def falla(*a, **k):
        raise ConnectionError("sin red")

    monkeypatch.setattr(fits_engine, "DATA_DIR", tmp_path)
    monkeypatch.setattr(app.spherex_real_loader, "descargar_a_disco", falla)
    fits_engine.cargar_objetivo.cache_clear()
    try:
        assert TestClient(app.app).get("/spectrum/barnard").status_code == 503
    finally:
        fits_engine.cargar_objetivo.cache_clear()


def test_descargar_sin_wavelength(tmp_path, monkeypatch):
    recorte = {"imagen": np.ones((2, 2), "float32"), "mjd": "Desconocida",
               "wavelength": "N/A", "detector": 3, "header": fits.Header()}
    loader = app.spherex_real_loader
    monkeypatch.setattr(loader, "obtener_recortes_reales_spherex",
                        lambda *a, **k: ([recorte], "ok"))
    n, _ = loader.descargar_a_disco("1deg", "2deg", tmp_path)
    h = fits.open(next(tmp_path.glob("*.fits")))[0].header
    assert n == 1 and h["MJD-OBS"] == 0.0 and "WAVELEN" not in h


def test_wavelength_desde_sia(monkeypatch):
    from astropy.table import Table

    loader = app.spherex_real_loader
    tabla = Table({
        "energy_bandpassname": ["SPHEREx-D6"],
        "access_url": ["http://ejemplo/fits"],
        "em_min": [4.6e-6],
        "em_max": [4.8e-6],
        "t_min": [60000.0],
    })

    class Hdul:
        data = np.ones((2, 2), "float32")
        header = fits.Header()

        def __contains__(self, nombre):
            return False

        def __getitem__(self, i):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(loader.fetchers, "spherex",
                        lambda *a, **k: (tabla, "spherex_dr1"))
    monkeypatch.setattr(loader.fits, "open", lambda *a, **k: Hdul())
    recortes, _ = loader.obtener_recortes_reales_spherex("1deg", "2deg")
    assert recortes[0]["wavelength"] == pytest.approx(4.7)


def test_seleccion_cubre_detectores():
    from astropy.table import Table

    t = Table({"energy_bandpassname": ["SPHEREx-D1"] * 5 + ["SPHEREx-D6"] * 5})
    sel = app.spherex_real_loader._seleccion_por_detector(t, 4)
    dets = {app.spherex_real_loader._detector(n) for n in sel["energy_bandpassname"]}
    assert dets == {1, 6} and len(sel) == 4


def test_onda_bilineal():
    import numpy as np

    X = np.array([1, 10]); Y = np.array([1, 10])
    V = np.array([[1.0, 2.0], [3.0, 4.0]])
    calib = (X, Y, V)
    assert app.spherex_real_loader._onda_en_pixel(calib, 1, 1) == pytest.approx(1.0)
    assert app.spherex_real_loader._onda_en_pixel(calib, 10, 10) == pytest.approx(4.0)
    assert app.spherex_real_loader._onda_en_pixel(calib, 5.5, 5.5) == pytest.approx(2.5)


def test_pixel_plano():
    h = fits.Header({"NAXIS1": 15, "NAXIS2": 15,
                     "CRPIX1A": -1625.0, "CRPIX2A": -72.0,
                     "CDELT1A": 1.0, "CDELT2A": 1.0,
                     "CRVAL1A": 0.0, "CRVAL2A": 0.0})
    assert app.spherex_real_loader._pixel_plano(h) == (1633.0, 80.0)
