# lista-iptv-bo 🇧🇴

🇧🇷 [Português](README.md) · 🇧🇴 **Español**

[![Atualizar lista IPTV](https://github.com/$repo/actions/workflows/update-iptv.yml/badge.svg)](https://github.com/$repo/actions/workflows/update-iptv.yml)
[![Testes](https://github.com/$repo/actions/workflows/tests.yml/badge.svg)](https://github.com/$repo/actions/workflows/tests.yml)

Lista IPTV de canales de televisión de **Bolivia**, armada a partir de transmisiones públicas disponibles en internet. Los canales se recopilan de fuentes abiertas y se verifican automáticamente (HTTP, estructura de la playlist HLS y segmentos de video). GitHub Actions regenera las listas M3U cada 6 horas.

> Este archivo se genera automáticamente a partir de `config/readme_template.es.md`. Edita la plantilla, no el README.

## 📊 Estado actual

| | |
|---|---|
| Canales encontrados | **$channels_total** |
| Canales en la lista principal | **$channels_main** |
| Canales en línea en la última verificación | **$channels_online** |
| Streams en línea / total | **$streams_online / $streams_total** |
| Última actualización | **$updated_at** |

## 📺 Listas M3U

| Lista | Contenido | URL |
|---|---|---|
| `bolivia.m3u` | **Principal**: un stream por canal, solo canales que pasaron la verificación (tolera caídas de hasta 48 h) | $raw_main |
| `bolivia-online.m3u` | Todos los streams confirmados en línea en la última ejecución, incluidos los alternativos (`Alt. 2`, `Alt. 3`…) | $raw_online |
| `bolivia-all.m3u` | Todos los canales y streams encontrados, incluso los que fallaron (marcados con `[Offline]`) | $raw_all |

Recomendación: usa **`bolivia.m3u`**. Si un canal no abre, búscalo en `bolivia-online.m3u`, que trae URLs alternativas.

## ▶️ Cómo usar

### VLC (Windows, macOS, Linux, Android)
1. Abre VLC y ve a **Medio → Abrir ubicación de red** (Ctrl+N).
2. Pega la URL de la lista principal: `$raw_main`
3. Haz clic en **Reproducir** y abre la lista de reproducción (Ctrl+L) para elegir el canal.

### Kodi
1. Instala el complemento **PVR IPTV Simple Client** (Complementos → Instalar desde repositorio → Clientes PVR).
2. En **Configurar → General**, elige *Ubicación: Ruta remota (dirección de Internet)*.
3. En **URL de la lista M3U**, pega `$raw_main`.
4. Reinicia Kodi; los canales aparecen en **TV**.

### Fire TV / Fire Stick
1. Instala un reproductor IPTV compatible con M3U (por ejemplo **TiviMate**, **IPTV Smarters** o **VLC para Fire TV**) desde la tienda de Amazon o con la app *Downloader*.
2. Agrega una nueva lista de tipo **M3U / URL**.
3. Pega `$raw_main` y guarda.
4. Configura en la app la actualización automática de la lista (cada 12 o 24 h) para recibir las correcciones.

Las listas usan UTF-8 y la sintaxis M3U extendida estándar (`#EXTINF` con `tvg-id`, `tvg-name`, `tvg-logo` y `group-title`), compatible con VLC, Kodi, TiviMate, IPTV Smarters, OTT Navigator, GSE y otros reproductores HLS. Los nombres de los grupos dentro de las listas están en portugués (por ejemplo `Bolívia | Geral`).

## 🔄 Actualización automática

El workflow [`update-iptv.yml`](.github/workflows/update-iptv.yml) se ejecuta **cada 6 horas** (y también se puede ejecutar manualmente en *Actions → Atualizar lista IPTV → Run workflow*):

1. **Recopila** las playlists de las fuentes de [`config/sources.json`](config/sources.json) y de la lista curada [`config/manual.m3u`](config/manual.m3u).
2. **Filtra** las entradas fuera de alcance: canales no bolivianos, URLs con tokens temporales, DRM, páginas HTML (YouTube, Dailymotion, Facebook) y streams marcados como geobloqueados.
3. **Elimina duplicados** (por `tvg-id` y por nombre normalizado), conservando las URLs alternativas.
4. **Verifica** cada stream de forma asíncrona, con timeout, límite de concurrencia y reintento ante fallas temporales:
   - código de estado HTTP;
   - estructura de la playlist HLS (`#EXTM3U`, variantes, `#EXTINF`, `#EXT-X-TARGETDURATION`, detección de DRM);
   - descarga parcial del segmento de video más reciente, comprobando que sea contenido multimedia real (MPEG-TS, fMP4, AAC);
   - también reconoce manifiestos DASH (`.mpd`) y transmisiones MPEG-TS directas.
5. **Genera** las tres listas, [`data/channels.json`](data/channels.json) (estado e historial de cada stream) y [`data/report.json`](data/report.json) (resumen, entradas rechazadas y motivo de cada falla).
6. **Publica** los cambios en el repositorio. Si no cambió nada relevante, no hace commit (los datos se renuevan al menos una vez al día).

Protecciones ante fallas temporales:
- un canal que funcionó en las últimas 48 h sigue en la lista principal si falla por timeout o error del servidor;
- si una fuente se cae, se conservan sus canales y se usa la última copia en caché;
- si ningún stream responde (probable problema de red del ejecutor), los archivos no se modifican.

### Fuentes

| Fuente | Estado | Aceptadas | Rechazadas |
|---|---|---|---|
$source_table

Para agregar un canal, incluye la URL pública en `config/manual.m3u` (con `tvg-id`, `tvg-logo` y `group-title`) o agrega una nueva fuente en `config/sources.json`.

## 📋 Canales

| Canal | Categoría | Departamento | Estado | Streams en línea |
|---|---|---|---|---|
$channel_table

## 🛠️ Ejecutar localmente

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m pytest                 # pruebas
python -m src.main               # recopila, verifica y genera las listas
```

Estructura:

```text
.github/workflows/   update-iptv.yml (cada 6 h) y tests.yml
src/                 main.py, collector.py, validator.py, generator.py, channels.py
config/              sources.json, manual.m3u, readme_template.md, readme_template.es.md
data/                channels.json, report.json
playlists/           bolivia.m3u, bolivia-online.m3u, bolivia-all.m3u
tests/               pruebas automatizadas (pytest)
```

## ⚠️ Aviso

- Este proyecto **no aloja ningún contenido de video**: solo organiza enlaces a transmisiones que los propios canales o terceros ponen a disposición pública en internet.
- **La disponibilidad de los canales depende exclusivamente de los canales** y de los servidores de origen. Los streams pueden dejar de funcionar, cambiar de dirección o tener restricciones geográficas en cualquier momento.
- No se incluyen fuentes que exijan inicio de sesión, suscripción, tokens privados o DRM, ni que eludan restricciones geográficas.
- Todas las marcas y logotipos pertenecen a sus respectivos dueños. Si eres responsable de algún canal y deseas que se retire el enlace, abre un *issue*.
