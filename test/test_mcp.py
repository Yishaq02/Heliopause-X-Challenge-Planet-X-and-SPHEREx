import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp"))

import spherex_mcp as srv


def test_tools_registered():
    tools = asyncio.run(srv.mcp.list_tools())
    assert {
        "list_targets",
        "get_spectrum",
        "difference_image",
        "export_animation",
        "check_gaia",
        "search_spherex",
    } <= {t.name for t in tools}


def test_list_targets():
    r = srv.list_targets()
    assert len(r) == 5 and r[0]["id"] == "barnard"


def test_spectrum_102(datos):
    s = srv.get_spectrum("barnard")
    assert len(s["flux"]) == 102 and len(s["wavelengths"]) == 102


def test_objetivo_desconocido():
    with pytest.raises(ValueError, match="Objetivo desconocido"):
        srv.get_spectrum("nope")


def test_diff_index_invalido(datos):
    with pytest.raises(ValueError, match="fuera de rango"):
        srv.difference_image("barnard", a=99)


def test_diff_devuelve_png(datos):
    img, meta = srv.difference_image("barnard")
    assert img.data.startswith(b"\x89PNG")
    assert "mjd_nueva" in meta
