import numpy as np
from config import N_DETECTORES, N_CANALES, posicion, mjd_a_anio
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


def espectro(tid, ra, dec, pmra=0.0, pmdec=0.0, epoch=2000.0):
    """Espectro de un objetivo con FITS locales en data/<tid>/."""
    return espectro_de_epocas(cargar_objetivo(tid), ra, dec, pmra, pmdec, epoch)


def espectro_de_epocas(epocas, ra, dec, pmra=0.0, pmdec=0.0, epoch=2000.0):
    """102 valores: 6 detectores x 17 canales concatenados, ordenados por detector.

    La posicion se corrige por movimiento propio a la fecha de cada observacion.
    """
    t = {"ra": ra, "dec": dec, "pmra": pmra, "pmdec": pmdec, "epoch": epoch}
    por_det = {d: ([], []) for d in range(1, N_DETECTORES + 1)}
    for e in epocas:
        if e["detector"] in por_det:
            r, d = posicion(t, mjd_a_anio(e["mjd"]))
            por_det[e["detector"]][0].append(e["wavelength"])
            por_det[e["detector"]][1].append(flujo_en(e, r, d))
    wls, fls = [], []
    for d in range(1, N_DETECTORES + 1):
        w, f = _canales(*por_det[d])
        wls.append(w)
        fls.append(f)
    wl, fl = np.concatenate(wls), np.concatenate(fls)
    nulls = lambda a: [None if not np.isfinite(v) else float(v) for v in a]
    return {"wavelengths": nulls(wl), "flux": nulls(fl)}
