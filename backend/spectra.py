import numpy as np
from config import N_DETECTORES, N_CANALES
from fits_engine import cargar_objetivo, flujo_en


def _canales(wl, fl):
    """Reduce/interpola los puntos de un detector a N_CANALES valores."""
    wl, fl = np.asarray(wl, float), np.asarray(fl, float)
    ok = np.isfinite(wl) & np.isfinite(fl)
    wl, fl = wl[ok], fl[ok]
    if len(wl) == 0:
        return np.full(N_CANALES, np.nan), np.full(N_CANALES, np.nan)
    o = np.argsort(wl)
    wl, fl = wl[o], fl[o]
    rejilla = np.linspace(wl[0], wl[-1], N_CANALES)
    return rejilla, np.interp(rejilla, wl, fl)


def espectro(tid, ra, dec):
    """102 valores: 6 detectores x 17 canales concatenados, ordenados por detector."""
    por_det = {d: ([], []) for d in range(1, N_DETECTORES + 1)}
    for e in cargar_objetivo(tid):
        if e["detector"] in por_det:
            por_det[e["detector"]][0].append(e["wavelength"])
            por_det[e["detector"]][1].append(flujo_en(e, ra, dec))
    wls, fls = [], []
    for d in range(1, N_DETECTORES + 1):
        w, f = _canales(*por_det[d])
        wls.append(w)
        fls.append(f)
    wl, fl = np.concatenate(wls), np.concatenate(fls)
    nulls = lambda a: [None if not np.isfinite(v) else float(v) for v in a]
    return {"wavelengths": nulls(wl), "flux": nulls(fl)}
