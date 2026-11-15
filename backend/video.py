import shutil
import subprocess
import tempfile
from pathlib import Path
import numpy as np
from PIL import Image

from diff import diferencia, a_uint8, emparejar
from fits_engine import cargar_objetivo, submuestrear


def _rango(im):
    """Percentiles 1-99 de los pixeles validos (ignora NaN)."""
    v = np.asarray(im, float)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return 0.0, 1.0
    lo, hi = np.percentile(v, 1), np.percentile(v, 99)
    if not hi > lo:
        hi = lo + 1.0
    return float(lo), float(hi)


def normalizar(im, rango=None):
    """Estiramiento a uint8; usa `rango` (lo, hi) o los percentiles de la propia imagen."""
    lo, hi = rango if rango else _rango(im)
    a = np.nan_to_num(np.asarray(im, float), nan=lo)
    return np.clip((a - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)


def normalizar_lote(imagenes):
    """Un solo estiramiento para toda la secuencia (evita parpadeo entre cuadros)."""
    if not imagenes:
        return []
    rangos = [_rango(im) for im in imagenes]
    lo, hi = min(r[0] for r in rangos), max(r[1] for r in rangos)
    if not hi > lo:
        hi = lo + 1.0
    return [normalizar(im, (lo, hi)) for im in imagenes]


def frames_de_epocas(epocas, modo, sigma=3.0, detector=1, tol_um=0.02, min_dias=1.0, maximo=None):
    eps = sorted((e for e in epocas if e["detector"] == detector), key=lambda e: e["mjd"])
    if modo == "diff":
        pares = submuestrear(emparejar(eps, tol_um, min_dias), maximo)
        if not pares:
            raise ValueError("No hay pares de la misma banda espectral para calcular diferencia")
        return [a_uint8(diferencia(n["imagen"], v["imagen"], sigma)) for n, v in pares]
    if not eps:
        raise ValueError("No hay epocas de ese detector")
    return normalizar_lote([e["imagen"] for e in submuestrear(eps, maximo)])


def frames(tid, modo, sigma=3.0, detector=1, tol_um=0.02, min_dias=1.0, maximo=None):
    return frames_de_epocas(cargar_objetivo(tid), modo, sigma, detector, tol_um, min_dias, maximo)


def escalar(f, lado_min=480):
    """Agranda con vecino mas cercano (sin suavizar pixeles) hasta que el lado menor >= lado_min."""
    k = max(1, -(-lado_min // min(f.shape)))
    return np.kron(f, np.ones((k, k), dtype=f.dtype)) if k > 1 else f


def generar_mp4(tid, modo, fps, detector=1, maximo=None):
    """MP4 de un objetivo local. Devuelve (ruta_mp4, carpeta_temporal)."""
    return generar_mp4_de_epocas(cargar_objetivo(tid), modo, fps, detector, maximo=maximo)


def generar_mp4_de_epocas(epocas, modo, fps, detector=1, sigma=3.0, tol_um=0.02, min_dias=1.0,
                          maximo=None):
    """Devuelve (ruta_mp4, carpeta_temporal). El llamador debe borrar la carpeta."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg no esta instalado o no esta en el PATH")
    tmp = Path(tempfile.mkdtemp(prefix="mp4_"))
    try:
        fs = frames_de_epocas(epocas, modo, sigma, detector, tol_um, min_dias, maximo)
        h = min(f.shape[0] for f in fs) // 2 * 2
        w = min(f.shape[1] for f in fs) // 2 * 2
        for i, f in enumerate(fs):
            Image.fromarray(escalar(f[:h, :w]), "L").save(tmp / f"frame_{i:03d}.png")
        salida = tmp / "salida.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-framerate", str(fps), "-i", str(tmp / "frame_%03d.png"),
             "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-pix_fmt", "yuv420p", str(salida)],
            check=True, capture_output=True)
        return salida, tmp
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
