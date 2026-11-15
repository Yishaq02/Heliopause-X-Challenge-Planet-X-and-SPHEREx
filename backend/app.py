import shutil
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

import config
import spectra
import diff as dif
import video
import gaia_check
from fits_engine import cargar_objetivo

app = FastAPI(title="SPHEREx backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _target(tid):
    t = config.get_target(tid)
    if not t:
        raise HTTPException(404, f"Objetivo desconocido: {tid}")
    return t


def _epocas(tid):
    try:
        return cargar_objetivo(tid)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


@app.get("/targets")
def targets():
    return config.cargar_targets()


@app.get("/spectrum/{tid}")
def spectrum(tid: str):
    t = _target(tid)
    _epocas(tid)
    return spectra.espectro(tid, t["ra"], t["dec"])


@app.get("/diff/{tid}")
def diff(tid: str, a: int = -1, b: int = -2, detector: int = 1, sigma: float = Query(3.0, gt=0)):
    """Epoca a (nueva) - epoca b (vieja) del mismo detector. Indices como en una lista Python."""
    _target(tid)
    ep = [e for e in _epocas(tid) if e["detector"] == detector]
    try:
        nueva, vieja = ep[a]["imagen"], ep[b]["imagen"]
    except IndexError:
        raise HTTPException(400, "Indice de epoca fuera de rango")
    m8 = dif.a_uint8(dif.diferencia(nueva, vieja, sigma))
    return {"shape": list(m8.shape), "png_base64": dif.a_base64(m8),
            "mjd_nueva": ep[a]["mjd"], "mjd_vieja": ep[b]["mjd"]}


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
    return FileResponse(ruta, media_type="video/mp4", filename=f"{target}_{mode}.mp4",
                        background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True))


@app.get("/gaia-check")
def gaia(target: str | None = None, ra: float | None = None, dec: float | None = None,
         radius: float = 3.0):
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
