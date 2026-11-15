import shutil
import subprocess
import tempfile
from pathlib import Path
import numpy as np
from PIL import Image

from diff import diferencia, a_uint8
from fits_engine import cargar_objetivo


def frames(tid, modo, sigma=3.0, detector=1):
    imgs = [e["imagen"] for e in cargar_objetivo(tid) if e["detector"] == detector]
    if len(imgs) < 2 and modo == "diff":
        raise ValueError("Se necesitan al menos 2 epocas para diferencia")
    if modo == "diff":
        return [a_uint8(diferencia(imgs[i], imgs[i - 1], sigma)) for i in range(1, len(imgs))]
    out = []
    for im in imgs:
        im = np.nan_to_num(im)
        lo, hi = np.percentile(im, 1), np.percentile(im, 99)
        out.append(np.clip((im - lo) / (hi - lo + 1e-12) * 255, 0, 255).astype(np.uint8))
    return out


def generar_mp4(tid, modo, fps):
    """Devuelve (ruta_mp4, carpeta_temporal). El llamador debe borrar la carpeta."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg no esta instalado o no esta en el PATH")
    tmp = Path(tempfile.mkdtemp(prefix="mp4_"))
    try:
        fs = frames(tid, modo)
        h = min(f.shape[0] for f in fs) // 2 * 2
        w = min(f.shape[1] for f in fs) // 2 * 2
        for i, f in enumerate(fs):
            Image.fromarray(f[:h, :w], "L").save(tmp / f"frame_{i:03d}.png")
        salida = tmp / "salida.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-framerate", str(fps), "-i", str(tmp / "frame_%03d.png"),
             "-pix_fmt", "yuv420p", str(salida)],
            check=True, capture_output=True)
        return salida, tmp
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
