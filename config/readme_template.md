# lista-iptv-bo 🇧🇴

🇧🇷 **Português** · 🇧🇴 [Español](README.es.md)

[![Atualizar lista IPTV](https://github.com/$repo/actions/workflows/update-iptv.yml/badge.svg)](https://github.com/$repo/actions/workflows/update-iptv.yml)
[![Testes](https://github.com/$repo/actions/workflows/tests.yml/badge.svg)](https://github.com/$repo/actions/workflows/tests.yml)

Lista IPTV de canais de televisão da **Bolívia**, montada a partir de transmissões públicas disponíveis na internet. Os canais são coletados de fontes abertas, verificados automaticamente (HTTP, estrutura da playlist HLS e segmentos de vídeo) e as listas M3U são regeneradas pelo GitHub Actions a cada 6 horas.

> Este arquivo é gerado automaticamente a partir de `config/readme_template.md` (versão em espanhol: `config/readme_template.es.md`). Edite os modelos, não o README.

## 📊 Situação atual

| | |
|---|---|
| Canais encontrados | **$channels_total** |
| Canais na lista principal | **$channels_main** |
| Canais online na última verificação | **$channels_online** |
| Streams online / total | **$streams_online / $streams_total** |
| Última atualização | **$updated_at** |

## 📺 Listas M3U

| Lista | Conteúdo | URL |
|---|---|---|
| `bolivia.m3u` | **Principal** — um stream por canal, apenas canais que passaram na verificação (tolera instabilidades de até 48 h) | $raw_main |
| `bolivia-online.m3u` | Todos os streams confirmados online na última execução, incluindo alternativos (`Alt. 2`, `Alt. 3`…) | $raw_online |
| `bolivia-all.m3u` | Todos os canais e streams encontrados, inclusive os que falharam (marcados com `[Offline]`) | $raw_all |

Recomendação: use **`bolivia.m3u`**. Se um canal não abrir, procure-o em `bolivia-online.m3u`, que traz URLs alternativas.

## ▶️ Como usar

### VLC (Windows, macOS, Linux, Android)
1. Abra o VLC e vá em **Mídia → Abrir fluxo de rede** (Ctrl+N).
2. Cole a URL da lista principal: `$raw_main`
3. Clique em **Reproduzir** e abra a lista de reprodução (Ctrl+L) para escolher o canal.

### Kodi
1. Instale o add-on **PVR IPTV Simple Client** (Add-ons → Instalar a partir do repositório → Clientes PVR).
2. Em **Configurar → Geral**, escolha *Localização: Caminho remoto (endereço da Internet)*.
3. Em **URL da lista M3U**, cole `$raw_main`.
4. Reinicie o Kodi; os canais aparecem em **TV**.

### Fire TV / Fire Stick
1. Instale um player IPTV compatível com M3U (por exemplo **TiviMate**, **IPTV Smarters** ou **VLC para Fire TV**) pela loja da Amazon ou pelo app *Downloader*.
2. Adicione uma nova lista do tipo **M3U / URL**.
3. Cole `$raw_main` e salve.
4. Configure a atualização automática da lista no app (a cada 12 ou 24 h) para receber as correções.

As listas usam UTF-8 e sintaxe M3U estendida padrão (`#EXTINF` com `tvg-id`, `tvg-name`, `tvg-logo` e `group-title`), compatível com VLC, Kodi, TiviMate, IPTV Smarters, OTT Navigator, GSE e outros players HLS.

## 🔄 Atualização automática

O workflow [`update-iptv.yml`](.github/workflows/update-iptv.yml) roda **a cada 6 horas** (e pode ser executado manualmente em *Actions → Atualizar lista IPTV → Run workflow*):

1. **Coleta** as playlists das fontes em [`config/sources.json`](config/sources.json) e da lista curada [`config/manual.m3u`](config/manual.m3u).
2. **Filtra** entradas fora do escopo: canais não bolivianos, URLs com tokens temporários, DRM, páginas HTML (YouTube, Dailymotion, Facebook) e streams marcados como geobloqueados.
3. **Deduplica** canais (por `tvg-id` e por nome normalizado), preservando URLs alternativas.
4. **Verifica** cada stream de forma assíncrona, com timeout, limite de concorrência e nova tentativa em falhas temporárias:
   - status HTTP;
   - estrutura da playlist HLS (`#EXTM3U`, variantes, `#EXTINF`, `#EXT-X-TARGETDURATION`, detecção de DRM);
   - download parcial do segmento de vídeo mais recente, conferindo se é mídia real (MPEG-TS, fMP4, AAC);
   - manifestos DASH (`.mpd`) e transmissões MPEG-TS diretas também são reconhecidos.
5. **Gera** as três listas, [`data/channels.json`](data/channels.json) (estado e histórico de cada stream) e [`data/report.json`](data/report.json) (resumo, entradas rejeitadas e motivos das falhas).
6. **Publica** as alterações no repositório. Se nada relevante mudou, não há commit (os dados são renovados pelo menos uma vez por dia).

Proteções contra falhas temporárias:
- um canal que funcionou nas últimas 48 h continua na lista principal se falhar por timeout ou erro de servidor;
- se uma fonte ficar fora do ar, os canais dela são mantidos e a última cópia em cache é usada;
- se nenhum stream responder (provável problema de rede do executor), os arquivos não são alterados.

### Fontes

| Fonte | Status | Aceitas | Rejeitadas |
|---|---|---|---|
$source_table

Para adicionar um canal, inclua a URL pública em `config/manual.m3u` (com `tvg-id`, `tvg-logo` e `group-title`) ou uma nova fonte em `config/sources.json`.

## 📋 Canais

| Canal | Categoria | Departamento | Situação | Streams online |
|---|---|---|---|---|
$channel_table

## 🛠️ Executar localmente

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m pytest                 # testes
python -m src.main               # coleta, verifica e gera as listas
```

Estrutura:

```text
.github/workflows/   update-iptv.yml (a cada 6 h) e tests.yml
src/                 main.py, collector.py, validator.py, generator.py, channels.py
config/              sources.json, manual.m3u, readme_template.md
data/                channels.json, report.json
playlists/           bolivia.m3u, bolivia-online.m3u, bolivia-all.m3u
tests/               testes automatizados (pytest)
```

## ⚠️ Aviso

- Este projeto **não hospeda nenhum conteúdo de vídeo**: ele apenas organiza links para transmissões que as próprias emissoras ou terceiros disponibilizam publicamente na internet.
- **A disponibilidade dos canais depende exclusivamente das emissoras** e dos servidores de origem. Streams podem sair do ar, mudar de endereço ou sofrer restrições geográficas a qualquer momento.
- Não são incluídas fontes que exijam login, assinatura, tokens privados, DRM ou que contornem restrições geográficas.
- Todas as marcas e logotipos pertencem aos respectivos proprietários. Se você é responsável por algum canal e deseja a remoção do link, abra uma *issue*.
