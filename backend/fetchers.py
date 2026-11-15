#!/usr/bin/env python3
import astropy.units as u
from astroquery.ipac.irsa import Irsa
from astroquery.gaia import Gaia
from astroquery.skyview import SkyView

COLECCIONES_SPHEREX = ['spherex_dr1', 'spherex_qr3']


def spherex(coord, radio=10):
    """Consulta imágenes de SPHEREx; prueba cada colección hasta hallar resultados.

    Devuelve (tabla, nombre_coleccion). Si no hay resultados, tabla vacía y None.
    """
    tabla = None
    for coleccion in COLECCIONES_SPHEREX:
        try:
            tabla = Irsa.query_sia(pos=(coord, radio * u.arcsec), collection=coleccion)
        except Exception as e:
            print(f"[spherex] fallo consultando {coleccion}: {e}")
            continue
        if len(tabla) > 0:
            return tabla, coleccion
    return tabla, None


def gaia(coord, radio=30):
    """Descarga el catálogo astrométrico de Gaia DR3."""
    return Gaia.cone_search_async(coordinate=coord, radius=radio * u.arcsec).get_results()


def wise(coord, fov=176):
    """Descarga recortes FITS de WISE (bandas W1 y W2)."""
    return SkyView.get_images(position=coord, survey=['WISE 3.4', 'WISE 4.6'], radius=fov * u.arcsec)


def spherex_todas(coord, radio=10, reintentos=3):
    """Combina TODAS las colecciones (DR1 + QR3) en una sola tabla, sin duplicar obs_id.

    Reintenta cada coleccion ante errores transitorios. Devuelve (tabla, "dr1+qr3") o (None, None).
    """
    import time
    from astropy.table import vstack
    tablas, usadas, fallidas = [], [], []
    for coleccion in COLECCIONES_SPHEREX:
        for i in range(reintentos):
            try:
                t = Irsa.query_sia(pos=(coord, radio * u.arcsec), collection=coleccion)
                if len(t) > 0:
                    tablas.append(t)
                    usadas.append(coleccion)
                break
            except Exception as e:
                print(f"[spherex] {coleccion} intento {i + 1}: {str(e)[:80]}")
                time.sleep(3)
        else:
            fallidas.append(coleccion)
    if fallidas:
        raise RuntimeError(f"colecciones sin respuesta: {fallidas}")
    if not tablas:
        return None, None
    tabla = vstack(tablas, join_type="inner") if len(tablas) > 1 else tablas[0]
    _, idx = __import__("numpy").unique(tabla["access_url"], return_index=True)
    return tabla[sorted(idx)], "+".join(usadas)
