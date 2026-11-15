"""Construye frames serializables (PNG base64 + metadatos) para el frontend."""
import numpy as np

from diff import a_base64, a_uint8, diferencia, emparejar
from fits_engine import submuestrear
from video import normalizar, normalizar_lote


def _num(v):
    """float finito o None (JSON no admite NaN/inf)."""
    v = float(v)
    return v if np.isfinite(v) else None


def _flag_bits(e):
    """{bit: fraccion de pixeles con ese bit activo}. None si no hay extension FLAGS.

    No se interpreta el significado de cada bit (ver el Explanatory Supplement de SPHEREx): algunos
    estan activos en todos los pixeles y son informativos, no indican contaminacion.
    """
    f = e.get("flags")
    if f is None:
        return None
    f = np.asarray(f).astype(np.int64)
    out = {}
    for b in range(32):
        frac = float(((f >> b) & 1).mean())
        if frac > 0:
            out[str(b)] = round(frac, 3)
    return out


def _media_sin_nan(imagenes):
    """Media por pixel ignorando NaN; NaN donde no hay ningun dato."""
    pila = np.stack([np.asarray(im, np.float32) for im in imagenes])
    cuenta = np.isfinite(pila).sum(axis=0)
    suma = np.nansum(pila, axis=0)
    return np.divide(suma, cuenta, out=np.full(cuenta.shape, np.nan, np.float32), where=cuenta > 0)


def construir(epocas, modo="normal", detector=1, sigma=3.0, tol_um=0.02, min_dias=1.0,
              maximo=None):
    """Devuelve lista de dicts {mjd, wavelength, detector, png_base64, flag_bits,...}.

    modo: 'normal' (un frame por epoca), 'diff' (nueva - vieja, misma banda) o 'stack' (media).
    `maximo` limita cuantos cuadros se devuelven (normal/diff); el apilado usa todas las epocas.
    """
    eps = sorted((e for e in epocas if e["detector"] == detector), key=lambda e: e["mjd"])
    if not eps:
        raise ValueError("No hay epocas de ese detector")

    if modo == "normal":
        visibles = submuestrear(eps, maximo)
        imagenes = normalizar_lote([e["imagen"] for e in visibles])
        return [{"mjd": e["mjd"], "wavelength": _num(e["wavelength"]), "detector": detector,
                 "flag_bits": _flag_bits(e), "shape": list(e["imagen"].shape),
                 "png_base64": a_base64(im)} for e, im in zip(visibles, imagenes)]

    if modo == "diff":
        pares = submuestrear(emparejar(eps, tol_um, min_dias), maximo)
        if not pares:
            raise ValueError("No hay pares de la misma banda espectral con esos parametros")
        out = []
        for nueva, vieja in pares:
            m8 = a_uint8(diferencia(nueva["imagen"], vieja["imagen"], sigma))
            out.append({"mjd": nueva["mjd"], "mjd_vieja": vieja["mjd"],
                        "wavelength": _num(nueva["wavelength"]), "detector": detector,
                        "flag_bits": _flag_bits(nueva), "shape": list(m8.shape),
                        "png_base64": a_base64(m8)})
        return out

    if modo == "stack":
        # Apilado de banda ancha: se mezclan longitudes de onda y se reporta el rango.
        h = min(e["imagen"].shape[0] for e in eps)
        w = min(e["imagen"].shape[1] for e in eps)
        media = _media_sin_nan([e["imagen"][:h, :w] for e in eps])
        wls = np.array([e["wavelength"] for e in eps], float)
        wls = wls[np.isfinite(wls)]
        return [{"mjd": float(np.mean([e["mjd"] for e in eps])),
                 "wavelength": _num(np.mean(wls)) if wls.size else None,
                 "wavelength_min": _num(wls.min()) if wls.size else None,
                 "wavelength_max": _num(wls.max()) if wls.size else None,
                 "detector": detector, "n_apilados": len(eps), "flag_bits": None,
                 "shape": [h, w], "png_base64": a_base64(normalizar(media))}]

    raise ValueError("modo debe ser normal, diff o stack")
