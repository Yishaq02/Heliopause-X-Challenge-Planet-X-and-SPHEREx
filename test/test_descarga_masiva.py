import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

import descarga_masiva  # noqa: E402


def test_filtra_ids_y_pasa_parametros(monkeypatch, tmp_path):
    objetivos = [
        {"id": "a", "ra": 10.0, "dec": 20.0, "pmra": 1.0, "pmdec": 2.0, "epoch": 2016.0},
        {"id": "b", "ra": 30.0, "dec": -40.0},
        {"id": "cero", "ra": 0.0, "dec": 0.0},
    ]
    monkeypatch.setattr(descarga_masiva.config, "cargar_targets", lambda: objetivos)
    monkeypatch.setattr(descarga_masiva.config, "DATA_DIR", tmp_path)
    vistos = []

    def falso(ra, dec, **k):
        vistos.append((ra, dec, k))
        k["carpeta"].mkdir(parents=True, exist_ok=True)
        (k["carpeta"] / "x.fits").write_bytes(b"x")
        return [k["carpeta"] / "x.fits"], []
    monkeypatch.setattr(descarga_masiva.cutouts, "obtener", falso)

    assert descarga_masiva.main(["a", "--max", "7", "--fov", "60"]) == 0
    assert len(vistos) == 1
    ra, dec, k = vistos[0]
    assert (ra, dec) == (10.0, 20.0)
    assert k["fov"] == 60 and k["maximo"] == 7
    assert k["pmra"] == 1.0 and k["pmdec"] == 2.0 and k["epoch"] == 2016.0
    assert k["carpeta"] == tmp_path / "a"


def test_id_desconocido(monkeypatch):
    monkeypatch.setattr(descarga_masiva.config, "cargar_targets", lambda: [{"id": "a", "ra": 1, "dec": 2}])
    assert descarga_masiva.main(["nope"]) == 2


def test_fov_invalido(monkeypatch):
    monkeypatch.setattr(descarga_masiva.config, "cargar_targets", lambda: [{"id": "a", "ra": 1, "dec": 2}])
    assert descarga_masiva.main(["a", "--fov", "5"]) == 2


def test_max_invalido(monkeypatch):
    monkeypatch.setattr(descarga_masiva.config, "cargar_targets", lambda: [{"id": "a", "ra": 1, "dec": 2}])
    assert descarga_masiva.main(["a", "--max", "0"]) == 2


def test_fallo_de_irsa_devuelve_1(monkeypatch, tmp_path):
    monkeypatch.setattr(descarga_masiva.config, "cargar_targets", lambda: [{"id": "a", "ra": 1, "dec": 2}])
    monkeypatch.setattr(descarga_masiva.config, "DATA_DIR", tmp_path)

    def boom(*a, **k):
        raise RuntimeError("caido")
    monkeypatch.setattr(descarga_masiva.cutouts, "obtener", boom)
    assert descarga_masiva.main(["a"]) == 1


def test_fallos_parciales_devuelven_1(monkeypatch, tmp_path):
    monkeypatch.setattr(descarga_masiva.config, "cargar_targets", lambda: [{"id": "a", "ra": 1, "dec": 2}])
    monkeypatch.setattr(descarga_masiva.config, "DATA_DIR", tmp_path)

    def con_fallos(*a, **k):
        k["carpeta"].mkdir(parents=True, exist_ok=True)
        (k["carpeta"] / "ok.fits").write_bytes(b"x")
        return [k["carpeta"] / "ok.fits"], ["fallo: 503"]
    monkeypatch.setattr(descarga_masiva.cutouts, "obtener", con_fallos)
    assert descarga_masiva.main(["a"]) == 1
