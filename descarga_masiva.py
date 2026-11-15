#!/usr/bin/env python3
"""Descarga recortes de SPHEREx (IRSA) a data/<id>/ para los objetivos de targets.json.

Wrapper de backend/cutouts: consulta SIA DR1+QR3, baja recortes IMAGE+FLAGS con WAVELEN,
centra por movimiento propio en la fecha de cada observacion y reintenta ante 502/503.

Uso:
    py -3.12 descarga_masiva.py [id ...] [--max 120] [--fov 90] [--reintentos 6]

Sin ids baja todos los objetivos. Es idempotente: los FITS que ya existen se conservan.
"""
import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ / "backend"))

import config  # noqa: E402
import cutouts  # noqa: E402


def _parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("ids", nargs="*", help="ids de targets.json (vacio = todos)")
    p.add_argument("--max", type=int, default=cutouts.DESCARGAS, help="imagenes por objetivo")
    p.add_argument("--fov", type=float, default=90.0, help="campo en arcsec (30-300)")
    p.add_argument("--reintentos", type=int, default=6, help="reintentos de la consulta SIA")
    return p


def _contar(carpeta):
    return len(list(carpeta.glob("*.fits"))) if carpeta.is_dir() else 0


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        cutouts.validar(0.0, 0.0, args.fov)
    except ValueError as e:
        print(f"[ERROR] {e}", flush=True)
        return 2
    if args.max < 1:
        print("[ERROR] --max debe ser >= 1", flush=True)
        return 2
    if args.max > cutouts.MAX_EPOCAS:
        print(f"[aviso] --max {args.max} se limita a {cutouts.MAX_EPOCAS} por objetivo", flush=True)

    objetivos = config.cargar_targets()
    if args.ids:
        deseados = set(args.ids)
        objetivos = [t for t in objetivos if t["id"] in deseados]
        faltan = deseados - {t["id"] for t in objetivos}
        if faltan:
            print(f"[ERROR] ids desconocidos: {', '.join(sorted(faltan))}", flush=True)
            return 2
    if not objetivos:
        print("[ERROR] no hay objetivos que descargar", flush=True)
        return 2

    fallos_total = 0
    for t in objetivos:
        if t["ra"] == 0 and t["dec"] == 0:
            print(f"[omitido] {t['id']}: coordenadas sin definir", flush=True)
            continue
        destino = config.DATA_DIR / t["id"]
        antes = _contar(destino)
        print(f"[{t['id']}] consultando IRSA...", flush=True)
        try:
            rutas, fallos = cutouts.obtener(
                t["ra"], t["dec"], fov=args.fov, detector=None, maximo=args.max,
                pmra=t.get("pmra", 0.0), pmdec=t.get("pmdec", 0.0),
                epoch=t.get("epoch", 2000.0), carpeta=destino,
                reintentos_consulta=args.reintentos)
        except (LookupError, ValueError, RuntimeError) as e:
            print(f"  [ERROR] {e}", flush=True)
            fallos_total += 1
            continue
        despues = _contar(destino)
        nuevos = max(0, despues - antes)
        print(f"  {len(rutas)} imagenes ({nuevos} nuevas, {despues} en total), "
              f"{len(fallos)} fallos", flush=True)
        for f in fallos:
            print(f"    FALLO {f[:120]}", flush=True)
        fallos_total += len(fallos)

    if fallos_total:
        print(f"\nTerminado con {fallos_total} fallo(s); vuelve a ejecutar para reintentar.", flush=True)
        return 1
    print("\nDataset listo.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
