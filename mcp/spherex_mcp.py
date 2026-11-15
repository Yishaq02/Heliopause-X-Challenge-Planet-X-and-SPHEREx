#!/usr/bin/env python3
"""Servidor MCP del proyecto SPHEREx / Planet X.

Expone los datos y el motor del backend (FITS locales, espectros, diferencias,
vídeos y consultas a Gaia/IRSA) como herramientas para agentes. Transporte stdio.
"""

import contextlib
import json
import shutil
import sys
from pathlib import Path
from typing import Annotated, Any, Literal

BASE = Path(__file__).resolve().parent.parent  # raíz del repo
# Al final: si la raíz fuera primero, la carpeta mcp/ eclipsaría al SDK "mcp".
sys.path.append(str(BASE))  # fetchers.py y spherex_real_loader.py viven en la raíz
sys.path.insert(0, str(BASE / "backend"))  # backend/ usa imports planos (import config)

import numpy as np
from pydantic import Field

# astroquery.gaia imprime un aviso en stdout al importarse: eso corrompería el
# protocolo JSON-RPC por stdio, así que lo redirigimos a stderr.
with contextlib.redirect_stdout(sys.stderr):
    import astropy.units as u
    from astropy.coordinates import SkyCoord
    from mcp.server.mcpserver import MCPServer, Image

    import config
    import diff as dif
    import fetchers
    import gaia_check
    import spectra
    import video
    from fits_engine import cargar_objetivo
    from spherex_real_loader import obtener_recortes_reales_spherex

mcp = MCPServer("spherex_mcp")

EXPORT_DIR = BASE / "exports"


def _target(tid: str) -> dict:
    t = config.get_target(tid)
    if not t:
        raise ValueError(
            f"Objetivo desconocido '{tid}'. Usa list_targets() para ver los válidos."
        )
    return t


def _epocas(tid: str) -> tuple[dict, list[dict]]:
    t = _target(tid)
    try:
        return t, cargar_objetivo(tid)
    except FileNotFoundError as e:
        raise ValueError(
            f"No hay FITS para '{tid}' en {config.DATA_DIR / tid}/. "
            f"Copia los archivos .fits del objetivo ahí y reintenta."
        ) from e


def _val(v: Any) -> Any:
    """Convierte escalares numpy/bytes de una tabla astropy a JSON."""
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, bytes):
        return v.decode(errors="replace")
    if isinstance(v, float) and not np.isfinite(v):
        return None
    return v


@mcp.tool(
    annotations={
        "title": "Listar objetivos",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
def list_targets() -> list[dict]:
    """Lista los objetivos del proyecto con sus coordenadas.

    Returns:
        list[dict]: [{"id": str, "nombre": str, "ra": float (deg), "dec": float (deg)}, ...]
    """
    return config.cargar_targets()


@mcp.tool(
    annotations={
        "title": "Espectro 102 canales",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
def get_spectrum(
    target_id: Annotated[
        str, Field(description="id de list_targets(), p. ej. 'barnard'")
    ],
) -> dict:
    """Espectro del objetivo: 6 detectores x 17 canales concatenados (102 puntos).

    Lee los FITS locales de data/<target_id>/. Los valores no finitos se devuelven como null.

    Returns:
        dict: {"wavelengths": list[float | None] (102), "flux": list[float | None] (102)}
    """
    t, _ = _epocas(target_id)
    return spectra.espectro(target_id, t["ra"], t["dec"])


@mcp.tool(
    structured_output=False,
    annotations={
        "title": "Imagen diferencia entre épocas",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def difference_image(
    target_id: Annotated[
        str, Field(description="id de list_targets(), p. ej. 'barnard'")
    ],
    a: Annotated[
        int,
        Field(description="Índice de la época nueva (como lista Python, p. ej. -1)"),
    ] = -1,
    b: Annotated[int, Field(description="Índice de la época vieja (p. ej. -2)")] = -2,
    detector: Annotated[int, Field(description="Detector 1..6", ge=1)] = 1,
    sigma: Annotated[
        float, Field(description="Umbral en sigmas sobre el MAD", gt=0)
    ] = 3.0,
) -> list[Any]:
    """Resta nueva - vieja del mismo detector y muestra solo lo que cambia (|d| >= sigma*MAD).

    Devuelve la imagen PNG en negro para lo estático y texto con los MJD comparados.

    Returns:
        list: [Image PNG, str con mjd_nueva/mjd_vieja/shape]
    """
    _, ep = _epocas(target_id)
    ep = [e for e in ep if e["detector"] == detector]
    try:
        nueva, vieja = ep[a]["imagen"], ep[b]["imagen"]
    except IndexError:
        raise ValueError(
            f"Índice fuera de rango: hay {len(ep)} épocas del detector {detector}."
        )
    m8 = dif.a_uint8(dif.diferencia(nueva, vieja, sigma))
    meta = {
        "mjd_nueva": ep[a]["mjd"],
        "mjd_vieja": ep[b]["mjd"],
        "shape": list(m8.shape),
    }
    return [Image(data=dif.a_png(m8), format="png"), json.dumps(meta)]


@mcp.tool(
    annotations={
        "title": "Exportar vídeo MP4",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
def export_animation(
    target_id: Annotated[str, Field(description="id de list_targets()")],
    mode: Annotated[
        Literal["normal", "diff"],
        Field(description="'normal' = épocas; 'diff' = diferencias consecutivas"),
    ] = "normal",
    fps: Annotated[
        Literal[5, 10], Field(description="Fotogramas por segundo: 5 o 10")
    ] = 5,
) -> str:
    """Genera un MP4 con las épocas del detector 1 y devuelve su ruta.

    Requiere ffmpeg en el PATH. El archivo queda en exports/<target>_<mode>_<fps>fps.mp4.
    """
    _epocas(target_id)
    try:
        src, tmp = video.generar_mp4(target_id, mode, fps)
    except RuntimeError as e:
        raise ValueError(f"{e}. Instala ffmpeg y reintenta.") from e
    EXPORT_DIR.mkdir(exist_ok=True)
    dest = EXPORT_DIR / f"{target_id}_{mode}_{fps}fps.mp4"
    try:
        shutil.move(str(src), dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return f"MP4 generado: {dest}"


@mcp.tool(
    annotations={
        "title": "Comprobar fuente en Gaia",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def check_gaia(
    ra: Annotated[float, Field(description="Ascensión recta en grados")],
    dec: Annotated[float, Field(description="Declinación en grados")],
    radius_arcsec: Annotated[
        float, Field(description="Radio de búsqueda en arcsec", gt=0)
    ] = 3.0,
) -> dict:
    """Busca fuentes Gaia DR3 en la posición; sin fuente conocida => posible anomalía.

    Consulta Gaia en vivo (requiere red).

    Returns:
        dict: {"known": bool, "n": int, "nearest_arcsec": float | None, "anomaly": bool}
    """
    try:
        r = gaia_check.es_conocida(ra, dec, radius_arcsec)
    except Exception as e:
        raise ValueError(f"Gaia no disponible: {e}. Reintenta cuando haya red.") from e
    return {**r, "anomaly": not r["known"]}


@mcp.tool(
    annotations={
        "title": "Buscar observaciones SPHEREx",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def search_spherex(
    ra: Annotated[float, Field(description="Ascensión recta en grados")],
    dec: Annotated[float, Field(description="Declinación en grados")],
    radius_arcsec: Annotated[
        float, Field(description="Radio de búsqueda en arcsec", gt=0)
    ] = 10,
    download: Annotated[
        bool,
        Field(
            description="True para descargar recortes y devolver estadísticas por época"
        ),
    ] = False,
    max_epochs: Annotated[
        int, Field(description="Máximo de épocas a descargar", ge=1, le=20)
    ] = 6,
    fov_arcsec: Annotated[
        float, Field(description="Tamaño del recorte en arcsec", gt=0)
    ] = 90,
    limit: Annotated[
        int, Field(description="Filas de la tabla a listar", ge=1, le=100)
    ] = 20,
) -> dict:
    """Consulta IRSA por observaciones SPHEREx (DR1/QR3) en una coordenada.

    Sin download devuelve las filas de la tabla SIA. Con download descarga hasta
    max_epochs recortes (centrados, sin bajar el archivo completo) y resume cada uno.

    Returns:
        dict: {"collection", "count", "rows"} o, con download, además
        {"epochs": [{"mjd", "wavelength", "shape", "min", "max", "mean"}, ...]}
    """
    coord = SkyCoord(ra=ra * u.deg, dec=dec * u.deg)
    try:
        tabla, coleccion = fetchers.spherex(coord, radio=radius_arcsec)
    except Exception as e:
        raise ValueError(f"IRSA no disponible: {e}. Reintenta cuando haya red.") from e
    if not coleccion or tabla is None or len(tabla) == 0:
        return {
            "collection": None,
            "count": 0,
            "hint": "Sin observaciones SPHEREx en esa coordenada; prueba un radio mayor o usa check_gaia.",
        }
    cols = [
        c
        for c in ("access_url", "t_min", "mjd_obs", "wavelength")
        if c in tabla.colnames
    ]
    rows = [{c: _val(tabla[c][i]) for c in cols} for i in range(min(len(tabla), limit))]
    salida = {"collection": coleccion, "count": len(tabla), "rows": rows}
    if not download:
        return salida
    recortes, msg = obtener_recortes_reales_spherex(
        f"{ra}deg", f"{dec}deg", fov_arcsec=fov_arcsec, max_epocas=max_epochs
    )
    epocas = []
    for r in recortes:
        v = r["imagen"][np.isfinite(r["imagen"])]
        epocas.append(
            {
                "mjd": _val(r["mjd"]),
                "wavelength": _val(r["wavelength"]),
                "shape": list(r["imagen"].shape),
                "min": float(v.min()) if v.size else None,
                "max": float(v.max()) if v.size else None,
                "mean": float(v.mean()) if v.size else None,
            }
        )
    return {**salida, "message": msg, "epochs": epocas}


if __name__ == "__main__":
    mcp.run()
