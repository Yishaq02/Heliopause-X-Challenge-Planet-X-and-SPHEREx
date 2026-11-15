import numpy as np
from astropy.io import fits

import cutouts


class _Resp:
    status_code = 200

    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass


def _bytes_con_longitud_nan():
    import io
    h = fits.Header()
    h["DETECTOR"], h["MJD-OBS"] = 2, 60100.0
    hdul = fits.HDUList([fits.PrimaryHDU(), fits.ImageHDU(np.ones((15, 15), np.float32), h, name="IMAGE")])
    b = io.BytesIO()
    hdul.writeto(b)
    return b.getvalue()


def test_wavelen_nan_no_rompe_la_descarga(tmp_path, monkeypatch):
    """Regresion: un NaN en la longitud de onda hacia fallar la escritura del FITS."""
    monkeypatch.setattr(cutouts.requests, "get", lambda *a, **k: _Resp(_bytes_con_longitud_nan()))
    monkeypatch.setattr(cutouts, "WCS", lambda *a, **k: type("W", (), {
        "pixel_to_world_values": staticmethod(lambda x, y: (float("nan"),))})())
    out = tmp_path / "a.fits"
    r = cutouts.bajar_recorte({"access_url": "u", "t_min": 60000}, lambda a: (1, 2), 90, out)
    assert r == "ok" and out.exists()
    assert "WAVELEN" not in fits.getheader(out)
