#!/usr/bin/env python3
import urllib.request
from astropy.coordinates import SkyCoord
import fetchers

# Coordenada exacta de tu enlace de WiseView
COORD = SkyCoord(ra=133.786245, dec=-7.244372, unit='deg')


def paso(nombre, funcion):
    """Ejecuta un paso; si falla, informa y continúa con el siguiente."""
    try:
        funcion()
        print(f"[OK] {nombre}")
    except Exception as e:
        print(f"[ERROR] {nombre}: {e}")


def guardar_gaia():
    fetchers.gaia(COORD).write('gaia.csv', format='csv', overwrite=True)


def guardar_wise():
    imgs = fetchers.wise(COORD)
    imgs[0].writeto('wise_w1.fits', overwrite=True)
    imgs[1].writeto('wise_w2.fits', overwrite=True)


def guardar_spherex():
    tabla, coleccion = fetchers.spherex(COORD)
    if not coleccion:
        print("    Sin observaciones de SPHEREx en esta coordenada.")
        return
    urllib.request.urlretrieve(tabla['access_url'][0], 'spherex_0.fits')


paso("Gaia -> gaia.csv", guardar_gaia)
paso("WISE -> wise_w1/w2.fits", guardar_wise)
paso("SPHEREx -> spherex_0.fits", guardar_spherex)
print("Proceso terminado.")
