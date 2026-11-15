import base64
import shutil

import pytest
from fastapi.testclient import TestClient

import app
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
    assert cliente.get("/spectrum/epsilon_indi_b").status_code == 404


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
    monkeypatch.setattr(gaia_check, "es_conocida",
                        lambda ra, dec, r: {"known": False, "n": 0, "nearest_arcsec": None})
    r = cliente.get("/gaia-check?target=barnard").json()
    assert r["known"] is False and r["anomaly"] is True


def test_gaia_caida_da_503(cliente, monkeypatch):
    def falla(*a):
        raise ConnectionError("sin red")
    monkeypatch.setattr(gaia_check, "es_conocida", falla)
    assert cliente.get("/gaia-check?ra=1&dec=2").status_code == 503
