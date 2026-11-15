#!/usr/bin/env python3
"""Descarga recortes de SPHEREx (IRSA) a data/<id>/ para los objetivos de targets.json.

Uso:  py -3.12 backend/descargar_fits.py [id ...] [--max 1000] [--fov 90]
"""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor

import config
import cutouts

parser = argparse.ArgumentParser()
parser.add_argument("ids", nargs="*")
parser.add_argument("--max", type=int, default=1000)
parser.add_argument("--fov", type=float, default=90, help="arcsec")
args = parser.parse_args()

for t in config.cargar_targets():
    if args.ids and t["id"] not in args.ids:
        continue
    if t["ra"] == 0 and t["dec"] == 0:
        print(f"[omitido] {t['id']}: coordenadas sin definir")
        continue
    destino = config.DATA_DIR / t["id"]
    destino.mkdir(parents=True, exist_ok=True)
    for p in destino.glob("*.part"):
        p.unlink()
    pos_fn = lambda anio, t=t: config.posicion(t, anio)  # noqa: E731
    try:
        tabla = cutouts.consultar(*pos_fn(2025.9), fov=args.fov)
    except RuntimeError as e:
        print(f"[ERROR] {t['id']}: {e}; vuelve a ejecutar luego", flush=True)
        continue
    if tabla is None or len(tabla) == 0:
        print(f"[sin datos] {t['id']}")
        continue
    filas = cutouts.seleccionar(tabla, None, args.max)
    print(f"[{t['id']}] {len(tabla)} imagenes; bajando {len(filas)}", flush=True)
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(lambda f: cutouts.bajar_recorte(f, pos_fn, args.fov, destino / cutouts.nombre(f)),
                          filas))
    fallos = [(cutouts.nombre(f), r) for f, r in zip(filas, res) if r.startswith("fallo")]
    print(f"  {res.count('ok')} ok, {res.count('ya existe')} existentes, {len(fallos)} fallos", flush=True)
    for n, r in fallos:
        print(f"    FALLO {n}: {r[:100]}", flush=True)
