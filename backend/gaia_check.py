import astropy.units as u
from astropy.coordinates import SkyCoord
from astroquery.gaia import Gaia


def es_conocida(ra, dec, radio_arcsec=3.0):
    """True si hay al menos una fuente Gaia DR3 dentro del radio.

    Estrellas de alto movimiento propio pueden quedar fuera del radio; ajustar radio_arcsec.
    """
    coord = SkyCoord(ra * u.deg, dec * u.deg)
    res = Gaia.cone_search_async(coord, radius=radio_arcsec * u.arcsec).get_results()
    n = len(res)
    nearest = float(min(res["dist"]) * 3600) if n and "dist" in res.colnames else None
    return {"known": n > 0, "n": n, "nearest_arcsec": nearest}
