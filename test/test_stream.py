import io

import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS

import cutouts


@pytest.fixture(autouse=True)
def mapa_limpio(tmp_path, monkeypatch):
    monkeypatch.setattr(cutouts, "WCS_DIR", tmp_path / "_wcs")
    monkeypatch.setattr(cutouts, "_MAPAS", {})
    yield


def _wave_hdu(x, y, valores):
    valores = np.asarray(valores, dtype=float)
    dim = "(" + ",".join(str(s) for s in reversed(valores.shape)) + ")"
    return fits.BinTableHDU.from_columns([
        fits.Column(name="X", format=f"{len(x)}J", array=[np.asarray(x, dtype=int)]),
        fits.Column(name="Y", format=f"{len(y)}J", array=[np.asarray(y, dtype=int)]),
        fits.Column(name="VALUES", format=f"{valores.size}E", array=[valores], dim=dim),
    ], name="WCS-WAVE")


def _cabecera(det=2, mjd=60100.0):
    h = fits.Header()
    h["DETECTOR"], h["MJD-OBS"] = det, mjd
    h["WCSAXESW"] = 2
    h["CTYPE1W"], h["CTYPE2W"] = "WAVE-TAB", "WAVE-TAB"
    h["CUNIT1W"], h["CUNIT2W"] = "um", "um"
    h["CRPIX1W"], h["CRPIX2W"] = 0.0, 0.0
    h["CDELT1W"], h["CDELT2W"] = 1.0, 1.0
    h["CRVAL1W"], h["CRVAL2W"] = 1.0, 1.0
    h["PV1_3W"], h["PV2_3W"] = 1, 2
    h["PS1_0W"], h["PS2_0W"] = "WCS-WAVE", "WCS-WAVE"
    h["PS1_1W"], h["PS2_1W"] = "VALUES", "VALUES"
    h["PS1_2W"], h["PS2_2W"] = "X", "Y"
    return h


def _tabla_vals(n=4):
    x = np.arange(1, n + 1)
    y = np.arange(1, n + 1)
    vals = np.zeros((n, n, 2))
    vals[:, :, 0] = y[:, None] * 0.10 + x[None, :] * 0.01
    vals[:, :, 1] = 0.05
    return x, y, vals


def _fits(det=2, relleno=300):
    img = np.ones((4, 4), np.float32)
    h = _cabecera(det)
    x, y, vals = _tabla_vals()
    hdus = [fits.PrimaryHDU(), fits.ImageHDU(img, h, name="IMAGE"),
            fits.ImageHDU(np.zeros((4, 4), np.int32), name="FLAGS")]
    if relleno:
        hdus.append(fits.ImageHDU(np.zeros((relleno, relleno), np.float32), name="EPSF"))
    hdus.append(_wave_hdu(x, y, vals))
    b = io.BytesIO()
    fits.HDUList(hdus).writeto(b)
    return b.getvalue(), h, x, y, vals


def test_bytes_datos_imagen_y_tabla():
    assert cutouts._bytes_datos({"NAXIS": 0, "BITPIX": 8}) == 0
    assert cutouts._bytes_datos({"NAXIS": 2, "NAXIS1": 10, "NAXIS2": 10, "BITPIX": 32}) == 2880
    tabla = {"NAXIS": 2, "NAXIS1": 40, "NAXIS2": 3, "BITPIX": 8, "PCOUNT": 8}
    assert cutouts._bytes_datos(tabla) == 2880


def test_leer_exacto_detecta_truncado():
    with pytest.raises(EOFError):
        cutouts._leer_exacto(io.BytesIO(b"abc"), 5)


def test_de_bytes_sin_tabla_deja_lambda_nan():
    img = np.ones((3, 3), np.float32)
    h = fits.Header()
    h["DETECTOR"] = 1
    h["WCSAXESW"] = 2
    b = io.BytesIO()
    fits.HDUList([fits.PrimaryHDU(), fits.ImageHDU(img, h, name="IMAGE")]).writeto(b)
    im, hdr, flags = cutouts._de_bytes(b.getvalue(), 1)
    assert im.shape == (3, 3) and flags is None and "WAVELEN" not in hdr


def test_de_bytes_extrae_y_reusa_tabla(tmp_path):
    datos, h, x, y, vals = _fits()
    det = 2
    im, hdr, flags = cutouts._de_bytes(datos, det)
    assert flags is not None and np.isfinite(hdr["WAVELEN"])
    assert cutouts._cargar_mapa(det, "x") is not None
    esperado = WCS(h, fits.HDUList([fits.PrimaryHDU(), fits.ImageHDU(np.ones((4, 4)), h, name="IMAGE"),
                                    _wave_hdu(x, y, vals)]), key="W").pixel_to_world_values(1.5, 1.5)[0]
    assert abs(hdr["WAVELEN"] - esperado) < 1e-5
    # segunda vez ya no necesita la tabla en el archivo: sale de la cache
    sin_tabla = io.BytesIO()
    fits.HDUList([fits.PrimaryHDU(), fits.ImageHDU(np.ones((4, 4), np.float32), _cabecera(), name="IMAGE"),
                  fits.ImageHDU(np.zeros((4, 4), np.int32), name="FLAGS")]).writeto(sin_tabla)
    im2, hdr2, _ = cutouts._de_bytes(sin_tabla.getvalue(), det)
    assert abs(hdr2["WAVELEN"] - hdr["WAVELEN"]) < 1e-6


def test_leer_hasta_corta_tras_flags_si_hay_mapa(tmp_path):
    datos, h, x, y, vals = _fits()
    cutouts._guardar_mapa(2, "x", {"x": x.tolist(), "y": y.tolist(), "values": vals.tolist()})
    parcial = cutouts._leer_hasta(io.BytesIO(datos), 2)
    assert len(parcial) < len(datos) // 10
    with fits.open(io.BytesIO(parcial)) as hd:
        assert [e.name for e in hd] == ["PRIMARY", "IMAGE", "FLAGS"]
    _, hdr, _ = cutouts._de_bytes(parcial, 2)
    assert np.isfinite(hdr["WAVELEN"])


def test_leer_hasta_incluye_wave_y_guarda_mapa_si_falta(tmp_path):
    datos, h, x, y, vals = _fits()
    assert cutouts._cargar_mapa(2, "x") is None
    parcial = cutouts._leer_hasta(io.BytesIO(datos), 2)
    with fits.open(io.BytesIO(parcial)) as hd:
        assert "WCS-WAVE" in hd
    mapa = cutouts._cargar_mapa(2, "x")
    assert mapa is not None and np.allclose(mapa["values"], vals)
    _, hdr, _ = cutouts._de_bytes(parcial, 2)
    assert np.isfinite(hdr["WAVELEN"])


def test_descargar_cae_al_completo_si_el_stream_falla(tmp_path, monkeypatch):
    datos, *_ = _fits()
    llamadas = []

    class Resp:
        def __init__(self, raw):
            self.raw, self.content, self.status_code = raw, datos, 200

        def raise_for_status(self):
            pass

        def close(self):
            pass

    class RawRoto:
        def read(self, n):
            raise OSError("conexion cortada")

    def get(url, **k):
        llamadas.append(k.get("stream", False))
        return Resp(RawRoto()) if k.get("stream") else Resp(None)

    monkeypatch.setattr(cutouts.requests, "get", get)
    im, hdr, flags = cutouts._descargar("http://x/2/a.fits", 2)
    assert im.shape == (4, 4) and np.isfinite(hdr["WAVELEN"])
    assert llamadas == [True, False]


def test_hdu_wave_es_legible_por_astropy(tmp_path):
    x, y, vals = _tabla_vals(3)
    hdu = cutouts._hdu_wave({"x": x.tolist(), "y": y.tolist(), "values": vals.tolist()})
    assert hdu.name == "WCS-WAVE" and hdu.data["VALUES"].shape == (1, 3, 3, 2)
    assert np.allclose(hdu.data["VALUES"][0], vals)
