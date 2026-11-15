import io
import base64

import numpy as np
import pytest
from astropy.io import fits
from astropy.table import Table
from fastapi.testclient import TestClient

import app
import cutouts
import fits_engine
import frames as frm


# --- validacion -------------------------------------------------------------
@pytest.mark.parametrize("ra,dec,fov", [(-1, 0, 90), (360, 0, 90), (10, 91, 90), (10, -91, 90),
                                         (10, 0, 5), (10, 0, 400)])
def test_validar_rechaza(ra, dec, fov):
    with pytest.raises(ValueError):
        cutouts.validar(ra, dec, fov)


def test_validar_acepta_limites():
    cutouts.validar(0, -90, 30)
    cutouts.validar(359.99, 90, 300)


# --- seleccion de filas ------------------------------------------------------
URL = "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/2025W33_2C/l2b-v27/{det}/level2_{i}.fits"


def _tabla(n=30):
    filas = [{"access_url": URL.format(det=1 + i % 6, i=i), "t_min": float(60000 + i)} for i in range(n)]
    return Table(rows=filas)


def test_detector_de_url():
    assert cutouts.detector_de({"access_url": URL.format(det=4, i=1)}) == 4
    assert cutouts.detector_de({"access_url": "nada"}) is None


def test_nombre():
    assert cutouts.nombre({"access_url": URL.format(det=2, i=7) + "?center=1,2"}) == "level2_7.fits"


def test_seleccionar_filtra_detector_y_ordena():
    f = cutouts.seleccionar(_tabla(30), detector=3, maximo=100)
    assert len(f) == 5 and all(cutouts.detector_de(x) == 3 for x in f)
    assert [x["t_min"] for x in f] == sorted(x["t_min"] for x in f)


def test_seleccionar_limita_y_reparte_en_el_tiempo():
    f = cutouts.seleccionar(_tabla(60), detector=None, maximo=10)
    assert len(f) == 10
    assert f[0]["t_min"] == 60000 and f[-1]["t_min"] == 60059


# --- descarga de un recorte (HTTP simulado) ----------------------------------
def _fits_bytes(det=2, mjd=60100.0):
    img = np.ones((15, 15), np.float32)
    h = fits.Header()
    h["DETECTOR"], h["MJD-OBS"] = det, mjd
    h["WCSAXESW"] = 2  # evita que astropy lo trate como falta de WCS espectral
    hdul = fits.HDUList([fits.PrimaryHDU(), fits.ImageHDU(img, h, name="IMAGE"),
                         fits.ImageHDU(np.zeros((15, 15), np.int32), name="FLAGS")])
    b = io.BytesIO()
    hdul.writeto(b)
    return b.getvalue()


class _Resp:
    def __init__(self, content=b"", status=200):
        self.content, self.status_code = content, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_bajar_recorte_ya_existe(tmp_path):
    out = tmp_path / "a.fits"
    out.write_bytes(b"x")
    assert cutouts.bajar_recorte({"access_url": "u", "t_min": 60000}, lambda a: (1, 2), 90, out) == "ya existe"


def test_bajar_recorte_fallo_no_deja_archivos(tmp_path, monkeypatch):
    monkeypatch.setattr(cutouts.requests, "get", lambda *a, **k: _Resp(status=503))
    monkeypatch.setattr(cutouts.time, "sleep", lambda s: None)
    out = tmp_path / "a.fits"
    r = cutouts.bajar_recorte({"access_url": "u", "t_min": 60000}, lambda a: (1, 2), 90, out)
    assert r.startswith("fallo")
    assert not out.exists() and not list(tmp_path.glob("*.part"))


def test_bajar_recorte_usa_posicion_de_la_fecha(tmp_path, monkeypatch):
    vistos = []
    monkeypatch.setattr(cutouts.requests, "get", lambda url, **k: (vistos.append(url), _Resp(status=503))[1])
    monkeypatch.setattr(cutouts.time, "sleep", lambda s: None)
    cutouts.bajar_recorte({"access_url": "http://x/f.fits", "t_min": 51544.5 + 365.25 * 10},
                          lambda anio: (anio, -anio), 36, tmp_path / "a.fits", reintentos=1)
    assert "center=2010.0,-2010.0deg" in vistos[0] and "size=0.01deg" in vistos[0]


# --- obtener (IRSA simulado) -------------------------------------------------
def _fake_bajar(f, pos_fn, fov, out, reintentos=3):
    out.write_bytes(_fits_bytes(mjd=float(f["t_min"])))
    return "ok"


def test_obtener_flujo_completo(tmp_path, monkeypatch):
    monkeypatch.setattr(cutouts, "consultar", lambda ra, dec, **k: _tabla(30))
    monkeypatch.setattr(cutouts, "bajar_recorte", _fake_bajar)
    rutas, fallos = cutouts.obtener(10, 20, 60, detector=2, maximo=3, carpeta=tmp_path)
    assert len(rutas) == 3 and fallos == []
    assert all(p.exists() for p in rutas)


def test_obtener_sin_datos(tmp_path, monkeypatch):
    monkeypatch.setattr(cutouts, "consultar", lambda ra, dec, **k: None)
    with pytest.raises(LookupError):
        cutouts.obtener(10, 20, 60, carpeta=tmp_path)


def test_obtener_irsa_caido(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("caido")
    monkeypatch.setattr(cutouts, "consultar", boom)
    with pytest.raises(RuntimeError):
        cutouts.obtener(10, 20, 60, carpeta=tmp_path)


def test_obtener_valida_antes_de_consultar(tmp_path, monkeypatch):
    monkeypatch.setattr(cutouts, "consultar", lambda *a, **k: pytest.fail("no debia consultar"))
    with pytest.raises(ValueError):
        cutouts.obtener(999, 0, 60, carpeta=tmp_path)


def test_leer_archivos_trae_flags(tmp_path):
    (tmp_path / "a.fits").write_bytes(_fits_bytes())
    # el helper escribe IMAGE como extension; _leer la encuentra por nombre
    ep = fits_engine.leer_archivos([tmp_path / "a.fits"])[0]
    assert ep["detector"] == 2 and ep["flags"] is not None and ep["imagen"].shape == (15, 15)


# --- frames ------------------------------------------------------------------
def _ep(mjd, wl, val=1.0, det=1, flags=None):
    im = np.full((8, 8), val, np.float32)
    return {"mjd": mjd, "wavelength": wl, "detector": det, "imagen": im, "flags": flags}


def test_frames_normal():
    fs = frm.construir([_ep(10, 2.0), _ep(20, 2.0)], "normal")
    assert len(fs) == 2 and fs[0]["flag_bits"] is None
    assert base64.b64decode(fs[0]["png_base64"]).startswith(b"\x89PNG")


def test_frames_flag_bits_por_bit():
    flags = np.zeros((8, 8), int)
    flags[:2] = 0b101          # bits 0 y 2 en 2 de 8 filas
    flags[:, :] |= 1 << 21     # bit 21 en todos los pixeles
    fb = frm.construir([_ep(10, 2.0, flags=flags)], "normal")[0]["flag_bits"]
    assert fb == {"0": 0.25, "2": 0.25, "21": 1.0}


def test_frames_stack_es_un_frame():
    fs = frm.construir([_ep(10, 2.0), _ep(20, 3.0), _ep(30, 4.0, det=2)], "stack")
    assert len(fs) == 1 and fs[0]["n_apilados"] == 2


def test_frames_diff_estatico_es_negro():
    from PIL import Image
    fs = frm.construir([_ep(10, 2.0), _ep(20, 2.0)], "diff", min_dias=1)
    im = np.array(Image.open(io.BytesIO(base64.b64decode(fs[0]["png_base64"]))))
    assert fs[0]["mjd_vieja"] == 10 and not im.any()


@pytest.mark.parametrize("modo,eps", [("normal", []), ("diff", [_ep(10, 2.0)]), ("raro", [_ep(1, 1.0)])])
def test_frames_errores(modo, eps):
    with pytest.raises(ValueError):
        frm.construir(eps, modo)


# --- endpoints ---------------------------------------------------------------
@pytest.fixture
def cliente(datos):
    return TestClient(app.app)


def test_cutouts_local(cliente):
    r = cliente.get("/cutouts?target=barnard&detector=2&mode=normal").json()
    assert r["origen"] == "local" and r["n"] == 3 and r["frames"][0]["png_base64"]


def test_cutouts_diff_y_stack_local(cliente):
    assert cliente.get("/cutouts?target=barnard&mode=diff&min_dias=0.5").json()["n"] == 2
    s = cliente.get("/stack?target=barnard&detector=3").json()
    assert s["n"] == 1 and s["frames"][0]["n_apilados"] == 3


def test_cutouts_requiere_target_o_coords(cliente):
    assert cliente.get("/cutouts").status_code == 400


def test_cutouts_mode_invalido_y_objetivo_desconocido(cliente):
    assert cliente.get("/cutouts?target=barnard&mode=x").status_code == 400
    assert cliente.get("/cutouts?target=nope").status_code == 404
    assert cliente.get("/cutouts?target=barnard&detector=9").status_code == 422


def _live(monkeypatch, rutas=None, exc=None):
    def f(*a, **k):
        if exc:
            raise exc
        return rutas, []
    monkeypatch.setattr(cutouts, "obtener", f)


@pytest.mark.parametrize("exc,code", [(ValueError("mal"), 400), (LookupError("nada"), 404),
                                      (RuntimeError("irsa"), 503)])
def test_cutouts_vivo_mapea_errores(cliente, monkeypatch, exc, code):
    _live(monkeypatch, exc=exc)
    assert cliente.get("/cutouts?ra=10&dec=20").status_code == code


def test_cutouts_vivo_ok(cliente, monkeypatch, tmp_path):
    for i in range(3):
        (tmp_path / f"{i}.fits").write_bytes(_fits_bytes(det=1, mjd=60000 + i))
    _live(monkeypatch, rutas=sorted(tmp_path.glob("*.fits")))
    r = cliente.get("/cutouts?ra=10&dec=20&fov=60").json()
    assert r["origen"] == "irsa" and r["n"] == 3 and r["descargas_fallidas"] == 0


def test_cutouts_objetivo_sin_fits_cae_a_vivo(cliente, monkeypatch, tmp_path):
    (tmp_path / "a.fits").write_bytes(_fits_bytes(det=1))
    _live(monkeypatch, rutas=[tmp_path / "a.fits"])
    assert cliente.get("/cutouts?target=r_dra").json()["origen"] == "irsa"


def test_spectrum_vivo(cliente, monkeypatch, tmp_path):
    rutas = []
    for det in range(1, 7):
        for k in range(3):
            p = tmp_path / f"{det}_{k}.fits"
            p.write_bytes(_fits_bytes(det=det, mjd=60000 + k))
            rutas.append(p)
    _live(monkeypatch, rutas=rutas)
    s = cliente.get("/spectrum?ra=10&dec=20").json()
    assert len(s["flux"]) == 102 and s["origen"] == "irsa"


def test_export_mp4_vivo_valida_antes_de_descargar(cliente, monkeypatch):
    monkeypatch.setattr(cutouts, "obtener", lambda *a, **k: pytest.fail("no debia descargar"))
    assert cliente.get("/export-mp4?ra=10&dec=20&fps=7").status_code == 400


def test_frontend_servido():
    r = TestClient(app.app).get("/")
    assert r.status_code == 200 and "SPHEREx Time Viewer" in r.text
    assert TestClient(app.app).get("/app.js").status_code == 200


def test_frames_sin_longitud_de_onda_es_json_valido():
    import json
    fs = frm.construir([_ep(10, float('nan')), _ep(20, float('nan'))], 'normal')
    assert fs[0]['wavelength'] is None
    json.dumps(fs, allow_nan=False)
    st = frm.construir([_ep(10, float('nan'))], 'stack')
    assert st[0]['wavelength'] is None

