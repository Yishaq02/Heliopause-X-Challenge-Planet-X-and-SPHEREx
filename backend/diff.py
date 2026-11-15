import base64
import io
import numpy as np
from PIL import Image


def _alinear(a, b):
    h, w = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1])
    return a[:h, :w], b[:h, :w]


def diferencia(nueva, vieja, sigma=3.0):
    """Nueva - Vieja, centrada y umbralizada. Devuelve float32 con NaN donde falta dato.

    - Se restan la mediana de la diferencia (desfase global de fondo/calibracion).
    - Todo lo estatico (|d| < sigma*MAD) -> 0.
    - Un pixel sin dato en cualquiera de las dos imagenes queda NaN (no se trata como 0).
    """
    n, v = _alinear(nueva, vieja)
    ok = np.isfinite(n) & np.isfinite(v)
    out = np.full(n.shape, np.nan, np.float32)
    if not ok.any():
        return out
    d = n[ok].astype(np.float32) - v[ok].astype(np.float32)
    d -= np.median(d)
    mad = 1.4826 * np.median(np.abs(d))
    umbral = sigma * (mad if mad > 0 else 1e-12)
    d[np.abs(d) < umbral] = 0.0
    out[ok] = d
    return out


def a_uint8(m, pct=99.9):
    """Normaliza a 0-255 usando el percentil `pct` de |m|; NaN y cero quedan en negro.

    Escalar por el maximo haria que un solo pixel caliente aplastara el resto de la imagen.
    """
    a = np.abs(np.asarray(m, dtype=np.float32))
    out = np.zeros(a.shape, np.uint8)
    fin = np.isfinite(a)
    if not fin.any():
        return out
    hi = float(np.percentile(a[fin], pct))
    if not hi > 0:
        hi = float(a[fin].max())
    if not hi > 0:
        return out
    out[fin] = np.clip(a[fin] / hi * 255, 0, 255).astype(np.uint8)
    return out


def a_png(m8):
    buf = io.BytesIO()
    Image.fromarray(m8, "L").save(buf, "PNG")
    return buf.getvalue()


def a_base64(m8):
    return base64.b64encode(a_png(m8)).decode()


def emparejar(epocas, tol_um=0.02, min_dias=1.0):
    """Pares (nueva, vieja) de un mismo detector con la misma banda espectral.

    Para cada epoca busca la anterior (al menos min_dias antes) cuya longitud de onda
    difiera menos de tol_um; elige la de menor diferencia. Asi la resta refleja cambio
    en el tiempo y no cambio de color.
    """
    ordenadas = sorted(epocas, key=lambda e: e["mjd"])
    pares = []
    for i, nueva in enumerate(ordenadas):
        mejor, dmin = None, tol_um
        for vieja in ordenadas[:i]:
            if nueva["mjd"] - vieja["mjd"] < min_dias:
                continue
            d = abs(nueva["wavelength"] - vieja["wavelength"])
            if d <= dmin:
                mejor, dmin = vieja, d
        if mejor is not None:
            pares.append((nueva, mejor))
    return pares
