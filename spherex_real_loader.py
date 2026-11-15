#!/usr/bin/env python3
import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits

import fetchers


def obtener_recortes_reales_spherex(ra_str, dec_str, fov_arcsec=90, max_epocas=6):
    """Busca y descarga recortes de SPHEREx en IRSA para una coordenada.

    Devuelve (lista_de_recortes, mensaje).
    """
    coord = SkyCoord(ra_str, dec_str, frame='icrs')

    try:
        resultados, coleccion = fetchers.spherex(coord, radio=fov_arcsec)
    except Exception as e:
        return [], f"Error conectando a IRSA: {e}"

    if not coleccion:
        return [], "No se encontraron observaciones de SPHEREx en estas coordenadas."

    # Ordenar por fecha para crear la línea temporal
    for col in ('t_min', 'mjd_obs'):
        if col in resultados.colnames:
            resultados.sort(col)
            break
    else:
        print("[spherex] aviso: sin columna de fecha; no se ordena cronológicamente.")

    # Recorte en servidor (con unidades explícitas) para evitar bajar ~100 MB por archivo
    tamano = f"{fov_arcsec / 3600.0}deg"
    centro = f"{coord.ra.deg},{coord.dec.deg}deg"

    recortes = []
    for fila in resultados[:max_epocas]:
        url = f"{fila['access_url']}?center={centro}&size={tamano}"
        try:
            with fits.open(url, cache=True) as hdul:
                ext = 'IMAGE' if 'IMAGE' in hdul else 1
                datos = hdul[ext].data
                header = hdul[ext].header
                recortes.append({
                    "imagen": np.nan_to_num(datos, nan=0.0),
                    "mjd": header.get('MJD-OBS', 'Desconocida'),
                    "wavelength": header.get('WAVELEN', header.get('LAMBDA', 'N/A')),
                    "header": header,
                })
        except Exception as e:
            print(f"[spherex] no se pudo leer {url}: {e}")

    return recortes, f"Se cargaron {len(recortes)} épocas de SPHEREx ({coleccion})."
