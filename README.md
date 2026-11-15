# Heliopause X - Planet X and SPHEREx

Herramienta web para NASA Space Apps Challenge (track *Planet X and SPHEREx*): escribe unas coordenadas
(RA/Dec) y mira como cambia ese parche del cielo en las imagenes de SPHEREx, como un pequeno video, para
detectar objetos que se mueven.

## Requisitos
- Python 3.12 y `pip install -r requirements.txt`
- `ffmpeg` en el PATH (solo para exportar MP4; Windows: `winget install Gyan.FFmpeg`)

## Arrancar
```
py -3.12 -m uvicorn app:app --reload --app-dir backend
```
Abre http://127.0.0.1:8000/ (interfaz) o http://127.0.0.1:8000/docs (API).

La interfaz acepta parametros en la URL, util para incrustarla:
`/?ra=133.7951&dec=-7.2451&fov=90&detector=6&mode=diff` o `/?target=barnard`.

## Datos
- **Coordenadas libres:** el backend consulta IRSA (colecciones `spherex_dr1` y `spherex_qr3`), descarga
  recortes pequenos y los guarda en `data/_cache/`. La primera consulta tarda de segundos a un par de
  minutos; despues sale de la cache. Cada campo se baja una sola vez (120 imagenes repartidas en el
  tiempo) y lo comparten las vistas de imagenes y el espectro.
- **Los 5 objetivos del reto** (`backend/targets.json`): Barnard, Epsilon Indi B, WISE 0855, RW Aur, R Dra.
  Para tenerlos locales y que carguen al instante: `py -3.12 backend/descargar_fits.py [id ...]`
  (guarda en `data/<id>/`; las posiciones se corrigen por movimiento propio a la fecha de cada imagen).
  Desde la raiz, el alias `py -3.12 descarga_masiva.py [id ...] [--max 120] [--fov 90]` hace lo mismo
  reutilizando el backend; es idempotente (conserva los FITS existentes).

Cada recorte de IRSA pesa ~4 MB, casi todo la extension `EPSF`. El backend lee el cuerpo por partes y
**corta tras `FLAGS`** (~48 KB). La longitud de onda del centro se calcula con la tabla `WCS-WAVE` del
detector (identica en todas las visitas de una version), que se guarda una vez en `data/_wcs/`. Si la
tabla no existe, ese primer archivo se baja completo para obtenerla; el resto se corta.

Variables de entorno:
- `SPHEREX_RATE` (peticiones/min por IP, 60; 0 desactiva) y `SPHEREX_BURST` (20).
- `SPHEREX_CACHE_MB` (limite de `data/_cache`, 2048; 0 desactiva la purga al arrancar).
- `SPHEREX_CONCURRENCIA` (descargas simultaneas a IRSA, 6). Subirlo acelera el primer llenado pero
  multiplica los errores 503.

Limites: `fov` entre 30 y 300 arcsec (6.1"/px), `detector` 1-6, `max` hasta 150 imagenes.

## API
| Endpoint | Para que |
|---|---|
| `GET /targets` | Lista de objetivos |
| `GET /cutouts?target=ID` o `?ra=&dec=&fov=&detector=&mode=normal\|diff\|stack&max=&tol=&min_dias=` | Frames PNG en base64 |
| `GET /stack?...` | Apilado (media) de un detector, con rango de longitud de onda |
| `GET /spectrum?target=ID` o `?ra=&dec=` | Espectro de 102 valores (6 detectores x 17 canales) |
| `GET /diff/{id}?detector=&par=&min_dias=&sigma=` | Resta nueva - vieja (misma banda), lo estatico en 0 |
| `GET /export-mp4?target=ID` o `?ra=&dec=&mode=normal\|diff&fps=5\|10&detector=&max=&tol=&min_dias=` | Video MP4 |
| `GET /gaia-check?target=ID` o `?ra=&dec=&radius=` | `known` / `anomaly` segun Gaia DR3 |

Notas:
- El modo `diff` solo resta imagenes del **mismo detector y de la misma banda espectral**
  (`|dlambda| <= tol`, 0.02 um por defecto), para que la diferencia sea cambio en el tiempo y no de color.
  Antes de restar se quita la mediana (desfase global) y lo estatico queda en 0; los pixeles sin dato
  son `NaN` y no se pintan. En `normal` y `stack` se usan todas las bandas, con un estiramiento comun.
- `flag_bits` da la fraccion de pixeles con cada bit de `FLAGS` activo. No se interpreta su significado
  (consulta el *SPHEREx Explanatory Supplement*): algunos bits estan activos en todos los pixeles.
- El limite de difraccion de SPHEREx es ~6.1"/px: `fov` menor que 30" no aporta detalle y el backend lo
  rechaza. La linea de tiempo cubre ~1.4 anos (las visitas de SPHEREx).
- Un objeto con movimiento propio alto (p. ej. Barnard, ~10"/ano) solo queda centrado si se da su
  movimiento propio: usa `target=` o los parametros `pmra`/`pmdec` (mas/ano).
- `known: false` de Gaia no implica una anomalia real: objetos muy frios o debiles (p. ej. WISE 0855) no
  estan en Gaia.

## Pruebas
```
py -3.12 -m pytest test -q
```

## Estructura
```
descarga_masiva.py  Alias de raiz para poblar data/<id>/ (reutiliza backend/cutouts)
backend/   API FastAPI y logica (cutouts, diff, spectra, video, frames, gaia_check, fetchers)
frontend/  Interfaz HTML + JS sin dependencias, servida por FastAPI en /
test/      Pruebas unitarias (IRSA y Gaia simulados; una parte usa ffmpeg real si esta instalado)
data/      FITS locales y cache (ignorado por git)
```
