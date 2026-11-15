# Heliopause-X-Challenge-Planet-X-and-SPHEREx
Este es el repositorio de nuestro challengue de Space Apps Challenge Nasa. Con el track: Planet X and SPHEREx

## Servidor MCP

`mcp/spherex_mcp.py` expone el backend como herramientas MCP por stdio, reutilizando
los módulos existentes: `list_targets`, `get_spectrum`, `difference_image`,
`export_animation`, `check_gaia` y `search_spherex`.

```bash
python -m pip install -r requirements.txt
python mcp/spherex_mcp.py
```

Configuración en OpenCode (`opencode.json`):

```json
{
  "mcp": {
    "spherex": {
      "type": "local",
      "command": ["python", "/ruta/al/repo/mcp/spherex_mcp.py"],
      "enabled": true
    }
  }
}
```

Los objetivos y sus FITS se leen de `backend/targets.json` y `data/<id>/*.fits`.
Los MP4 exportados quedan en `exports/`.

## Backend HTTP

```bash
cd backend
uvicorn app:app --reload
```

| Ruta | Qué devuelve |
|---|---|
| `GET /targets` | Lista de objetivos |
| `GET /spectrum/{tid}` | 102 valores (6 detectores × 17 canales) |
| `GET /diff/{tid}` | PNG base64 de la resta entre épocas |
| `GET /export-mp4?target={tid}` | MP4 de la animación |
| `GET /gaia-check?target={tid}` | Fuente Gaia y flag `anomaly` |
| `GET /fits/{tid}` | Manifiesto de épocas con `fits_url` y `png_url` |
| `GET /fits/{tid}/{index}` | FITS original de esa época |
| `GET /fits/{tid}/{index}?format=png` | PNG estirado (1–99 %) para el visor |
| `POST /ingest/{tid}` | Descarga cutouts oficiales de IRSA a `data/<id>/` |

### Datos

No se versionan FITS. Si `data/<id>/` está vacío, la primera petición a
`/spectrum`, `/diff`, `/export-mp4` o `/fits` descarga cutouts oficiales de
SPHEREx desde IRSA con `spherex_real_loader.py` y los guarda en `data/<id>/`.
También se puede forzar:

```bash
curl -X POST 'http://127.0.0.1:8000/ingest/barnard'
curl -X POST 'http://127.0.0.1:8000/ingest/barnard?detector=6&max_epocas=102'
```

Los objetivos TODO con `ra=dec=0` devuelven 404. Si IRSA no responde, los
endpoints devuelven 503 con el motivo, no datos inventados.

Nota de alcance: el recorte de IRSA (`?center=...&size=...`) descarta la
extensión `WCS-WAVE`. El backend la recupera del L2 completo con HTTP `Range`
(~3.6 KB por detector) y calcula la longitud de onda real del píxel del
objetivo en cada época; como el barrido mueve el objetivo por el detector, las
épocas aportan λ distintas. Con `max_epocas=102` (17 por detector) se llenan
las 102 bandas con λ medidas, no nominales. Si IRSA no permite leer `WCS-WAVE`,
cae a la banda nominal de la tabla SIA.

### Tests

```bash
pytest
```

`test/conftest.py` genera FITS sintéticos en un directorio temporal y Gaia se
simula en `test_api.py`: la suite valida la lógica sin descargar FITS ni
consultar APIs. La integración real se prueba a mano con `POST /ingest/{tid}`.
