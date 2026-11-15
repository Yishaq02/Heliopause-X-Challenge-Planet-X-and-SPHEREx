import shutil
import sys
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask

import config
import fits_engine
import spectra
import diff as dif
import video
import gaia_check
from fits_engine import cargar_objetivo

sys.path.append(str(Path(__file__).resolve().parent.parent))
import spherex_real_loader  # noqa: E402  (loader oficial de IRSA, vive en la raíz)

app = FastAPI(title="SPHEREx backend")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


def _target(tid):
    t = config.get_target(tid)
    if not t:
        raise HTTPException(404, f"Objetivo desconocido: {tid}")
    return t


def _epocas(tid):
    try:
        return cargar_objetivo(tid)
    except FileNotFoundError as e:
        t = _target(tid)
        if t["ra"] == 0.0 and t["dec"] == 0.0:
            raise HTTPException(404, str(e))
        # Sin FITS locales: se bajan recortes oficiales de IRSA una sola vez.
        try:
            n, _ = spherex_real_loader.descargar_a_disco(
                f"{t['ra']}deg", f"{t['dec']}deg", config.DATA_DIR / tid
            )
        except Exception as err:
            raise HTTPException(
                503, f"Sin FITS locales y fallo al descargar de IRSA: {err}"
            )
        if n == 0:
            raise HTTPException(404, f"IRSA no devolvió observaciones para {tid}")
        cargar_objetivo.cache_clear()
        return cargar_objetivo(tid)


def _num(v):
    """NaN/inf no son JSON válido: se publican como null."""
    return float(v) if v == v and abs(v) != float("inf") else None


@app.get("/targets")
def targets():
    return config.cargar_targets()


@app.get("/fits/{tid}")
def fits_index(tid: str):
    """Manifiesto de épocas con URL para el FITS original y para su PNG."""
    _target(tid)
    ep = _epocas(tid)
    return {
        "target": tid,
        "count": len(ep),
        "epochs": [
            {
                "index": i,
                "archivo": e["archivo"],
                "detector": e["detector"],
                "mjd": e["mjd"],
                "wavelength": _num(e["wavelength"]),
                "fits_url": f"/fits/{tid}/{i}",
                "png_url": f"/fits/{tid}/{i}?format=png",
            }
            for i, e in enumerate(ep)
        ],
    }


@app.get("/fits/{tid}/{index}")
def fits_file(tid: str, index: int, format: Literal["fits", "png"] = "fits"):
    """Devuelve una época como FITS (por defecto) o como PNG estirado para el visor."""
    _target(tid)
    ep = _epocas(tid)
    if not 0 <= index < len(ep):
        raise HTTPException(400, f"index fuera de rango: hay {len(ep)} épocas")
    e = ep[index]
    if format == "png":
        return Response(
            dif.a_png(video.normalizar(e["imagen"])), media_type="image/png"
        )
    ruta = fits_engine.DATA_DIR / tid / e["archivo"]
    if not ruta.exists():
        raise HTTPException(404, f"No existe {ruta}")
    return FileResponse(ruta, media_type="image/fits", filename=e["archivo"])


@app.post("/ingest/{tid}")
def ingest(
    tid: str, detector: int | None = None, max_epocas: int = Query(102, ge=1, le=180)
):
    """Descarga cutouts oficiales de SPHEREx (IRSA) a data/<tid>/."""
    t = _target(tid)
    try:
        n, mensaje = spherex_real_loader.descargar_a_disco(
            f"{t['ra']}deg",
            f"{t['dec']}deg",
            config.DATA_DIR / tid,
            max_epocas=max_epocas,
            detector=detector,
        )
    except Exception as e:
        raise HTTPException(503, f"No se pudo descargar de IRSA: {e}")
    cargar_objetivo.cache_clear()
    return {"target": tid, "escritos": n, "mensaje": mensaje}


@app.get("/spectrum/{tid}")
def spectrum(tid: str):
    t = _target(tid)
    _epocas(tid)
    return spectra.espectro(tid, t["ra"], t["dec"])


@app.get("/diff/{tid}")
def diff(
    tid: str,
    a: int = -1,
    b: int = -2,
    detector: int = 1,
    sigma: float = Query(3.0, gt=0),
):
    """Epoca a (nueva) - epoca b (vieja) del mismo detector. Indices como en una lista Python."""
    _target(tid)
    ep = [e for e in _epocas(tid) if e["detector"] == detector]
    try:
        nueva, vieja = ep[a]["imagen"], ep[b]["imagen"]
    except IndexError:
        raise HTTPException(400, "Indice de epoca fuera de rango")
    m8 = dif.a_uint8(dif.diferencia(nueva, vieja, sigma))
    return {
        "shape": list(m8.shape),
        "png_base64": dif.a_base64(m8),
        "mjd_nueva": ep[a]["mjd"],
        "mjd_vieja": ep[b]["mjd"],
    }


@app.get("/export-mp4")
def export_mp4(target: str, mode: str = "normal", fps: int = 5):
    if mode not in ("normal", "diff"):
        raise HTTPException(400, "mode debe ser 'normal' o 'diff'")
    if fps not in config.FPS_VALIDOS:
        raise HTTPException(400, f"fps debe ser uno de {config.FPS_VALIDOS}")
    _target(target)
    _epocas(target)
    try:
        ruta, tmp = video.generar_mp4(target, mode, fps)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Error generando MP4: {e}")
    return FileResponse(
        ruta,
        media_type="video/mp4",
        filename=f"{target}_{mode}.mp4",
        background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True),
    )


@app.get("/gaia-check")
def gaia(
    target: str | None = None,
    ra: float | None = None,
    dec: float | None = None,
    radius: float = 3.0,
):
    if target:
        t = _target(target)
        ra, dec = t["ra"], t["dec"]
    if ra is None or dec is None:
        raise HTTPException(400, "Indica target o ra y dec")
    try:
        r = gaia_check.es_conocida(ra, dec, radius)
    except Exception as e:
        raise HTTPException(503, f"Gaia no disponible: {e}")
    return {**r, "anomaly": not r["known"]}
