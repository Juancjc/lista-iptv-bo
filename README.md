# lista-iptv-bo 🇧🇴

🇧🇷 **Português** · 🇧🇴 [Español](README.es.md)

[![Atualizar lista IPTV](https://github.com/Juancjc/lista-iptv-bo/actions/workflows/update-iptv.yml/badge.svg)](https://github.com/Juancjc/lista-iptv-bo/actions/workflows/update-iptv.yml)
[![Testes](https://github.com/Juancjc/lista-iptv-bo/actions/workflows/tests.yml/badge.svg)](https://github.com/Juancjc/lista-iptv-bo/actions/workflows/tests.yml)

Lista IPTV de canais de televisão da **Bolívia**, montada a partir de transmissões públicas disponíveis na internet. Os canais são coletados de fontes abertas, verificados automaticamente (HTTP, estrutura da playlist HLS e segmentos de vídeo) e as listas M3U são regeneradas pelo GitHub Actions a cada 6 horas.

> Este arquivo é gerado automaticamente a partir de `config/readme_template.md` (versão em espanhol: `config/readme_template.es.md`). Edite os modelos, não o README.

## 📊 Situação atual

| | |
|---|---|
| Canais encontrados | **81** |
| Canais na lista principal | **55** |
| Canais online na última verificação | **55** |
| Streams online / total | **80 / 135** |
| Última atualização | **25/10/2026 15:11 (horário da Bolívia, UTC−4)** |

## 📺 Listas M3U

| Lista | Conteúdo | URL |
|---|---|---|
| `bolivia.m3u` | **Principal** — um stream por canal, apenas canais que passaram na verificação (tolera instabilidades de até 48 h) | https://raw.githubusercontent.com/Juancjc/lista-iptv-bo/main/playlists/bolivia.m3u |
| `bolivia-online.m3u` | Todos os streams confirmados online na última execução, incluindo alternativos (`Alt. 2`, `Alt. 3`…) | https://raw.githubusercontent.com/Juancjc/lista-iptv-bo/main/playlists/bolivia-online.m3u |
| `bolivia-all.m3u` | Todos os canais e streams encontrados, inclusive os que falharam (marcados com `[Offline]`) | https://raw.githubusercontent.com/Juancjc/lista-iptv-bo/main/playlists/bolivia-all.m3u |

Recomendação: use **`bolivia.m3u`**. Se um canal não abrir, procure-o em `bolivia-online.m3u`, que traz URLs alternativas.

## ▶️ Como usar

### VLC (Windows, macOS, Linux, Android)
1. Abra o VLC e vá em **Mídia → Abrir fluxo de rede** (Ctrl+N).
2. Cole a URL da lista principal: `https://raw.githubusercontent.com/Juancjc/lista-iptv-bo/main/playlists/bolivia.m3u`
3. Clique em **Reproduzir** e abra a lista de reprodução (Ctrl+L) para escolher o canal.

### Kodi
1. Instale o add-on **PVR IPTV Simple Client** (Add-ons → Instalar a partir do repositório → Clientes PVR).
2. Em **Configurar → Geral**, escolha *Localização: Caminho remoto (endereço da Internet)*.
3. Em **URL da lista M3U**, cole `https://raw.githubusercontent.com/Juancjc/lista-iptv-bo/main/playlists/bolivia.m3u`.
4. Reinicie o Kodi; os canais aparecem em **TV**.

### Fire TV / Fire Stick
1. Instale um player IPTV compatível com M3U (por exemplo **TiviMate**, **IPTV Smarters** ou **VLC para Fire TV**) pela loja da Amazon ou pelo app *Downloader*.
2. Adicione uma nova lista do tipo **M3U / URL**.
3. Cole `https://raw.githubusercontent.com/Juancjc/lista-iptv-bo/main/playlists/bolivia.m3u` e salve.
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
| `iptv-org-bo` | ✅ OK | 65 | 30 |
| `iptv-org-streams-bo` | ✅ OK | 104 | 6 |
| `manual` | ✅ OK | 7 | 0 |
| `codemonchit0` | ✅ OK | 31 | 51 |
| `gatojustiniano` | ✅ OK | 31 | 50 |

Para adicionar um canal, inclua a URL pública em `config/manual.m3u` (com `tvg-id`, `tvg-logo` e `group-title`) ou uma nova fonte em `config/sources.json`.

## 📋 Canais

| Canal | Categoria | Departamento | Situação | Streams online |
|---|---|---|---|---|
| Abya Yala TV | Geral | La Paz | 🔴 Offline | 0/1 |
| Alegria TV | Música | — | 🔴 Offline | 0/1 |
| Amitel TV | Geral | — | 🟢 Online | 2/2 |
| As Contenidos | Geral | — | 🟢 Online | 1/1 |
| ATB | Geral | La Paz | 🟢 Online | 1/3 |
| Audiokiss | Música | — | 🟢 Online | 1/1 |
| Ayni TV | Geral | — | 🟢 Online | 1/2 |
| Bolivia Mix TV | Geral | — | 🟢 Online | 1/1 |
| Bolivia TV | TV Pública | La Paz | 🟢 Online | 2/3 |
| Bolivia TV 7.2 | TV Pública | La Paz | 🔴 Offline | 0/1 |
| Bolivisión | Geral | La Paz | 🔴 Offline | 0/2 |
| Bolivisión Santa Cruz | Geral | Santa Cruz | 🔴 Offline | 0/2 |
| Cadena A | Notícias | La Paz | 🟢 Online | 2/3 |
| Canal 15 Teleor | Geral | — | 🔴 Offline | 0/1 |
| Canal 56 Quiero TV | Geral | — | 🟢 Online | 1/1 |
| CEACOM TV | Geral | — | 🟢 Online | 2/2 |
| Cinerama Television | Entretenimento | — | 🔴 Offline | 0/1 |
| Coral TV | Geral | — | 🟢 Online | 3/3 |
| Cosmos TV | Geral | — | 🟢 Online | 1/1 |
| CTV Bolivia | Geral | — | 🔴 Offline | 0/4 |
| CVC | Religioso | — | 🔴 Offline | 0/1 |
| Delta TV | Geral | — | 🟢 Online | 1/1 |
| Dmoda Channel | Geral | — | 🟢 Online | 1/1 |
| El Deber TV | Notícias | Santa Cruz | 🟢 Online | 1/1 |
| F10 | Geral | — | 🟢 Online | 2/3 |
| FAP TV | Geral | — | 🟢 Online | 1/2 |
| FTV | Esportes | — | 🟢 Online | 1/1 |
| Gigavisión | Geral | — | 🟢 Online | 2/2 |
| Gigavisión La Paz | Geral | La Paz | 🟢 Online | 1/1 |
| Gigavisión Santa Cruz | Geral | Santa Cruz | 🟢 Online | 2/2 |
| Gogoplay TV | Geral | — | 🟢 Online | 1/1 |
| Imperial TV | Geral | — | 🟢 Online | 1/1 |
| Interactivo Television | Geral | — | 🔴 Offline | 0/2 |
| Palenque TV | Geral | — | 🟢 Online | 1/2 |
| PAT La Paz | Geral | La Paz | 🔴 Offline | 0/2 |
| PAT Santa Cruz | Geral | Santa Cruz | 🔴 Offline | 0/1 |
| Plus TLT | Geral | — | 🔴 Offline | 0/1 |
| Poder de Dios TV | Religioso | — | 🟢 Online | 1/2 |
| PTV Paceñísima | Geral | La Paz | 🟢 Online | 2/2 |
| Radio Centro | Geral | — | 🟢 Online | 1/1 |
| Radio Clasica TV | Música | — | 🟢 Online | 1/1 |
| Radio Kollasuyo | Geral | — | 🟢 Online | 1/1 |
| Radio Mega TV Amazonia | Geral | — | 🟢 Online | 1/1 |
| Radio Universitaria San Andrés | Universitário | La Paz | 🟢 Online | 1/1 |
| Red ADvenir TV | Religioso | — | 🔴 Offline | 0/2 |
| Red America TV | Geral | — | 🟢 Online | 1/1 |
| Red CCTV | Geral | — | 🟢 Online | 2/3 |
| Red DTV | Geral | — | 🔴 Offline | 0/1 |
| Red Rubi | Geral | — | 🟢 Online | 1/1 |
| Red Siglo XXI | Geral | — | 🔴 Offline | 0/1 |
| Red TV Shop | Compras | — | 🟢 Online | 1/1 |
| Red Uno | Geral | — | 🟢 Online | 1/2 |
| Red Uno La Paz | Geral | La Paz | 🟢 Online | 1/1 |
| Red Uno Santa Cruz | Geral | Santa Cruz | 🟢 Online | 2/2 |
| RTP | Geral | La Paz | 🟢 Online | 4/4 |
| Sol TV | Geral | — | 🔴 Offline | 0/1 |
| SPC Canal 15 | Geral | — | 🔴 Offline | 0/1 |
| Sucremanta TV | Geral | — | 🟢 Online | 1/1 |
| TDT Multimedia | Geral | — | 🟢 Online | 1/2 |
| Tele 6 | Geral | — | 🟢 Online | 1/1 |
| Tele Estrella | Geral | — | 🟢 Online | 2/2 |
| Tele Fe Bolivia | Geral | — | 🟢 Online | 1/1 |
| TransMedia | Geral | — | 🔴 Offline | 0/1 |
| TV Culturas | Cultural | — | 🔴 Offline | 0/1 |
| TV Latina | Geral | — | 🟢 Online | 3/3 |
| TV Off | Viagens | — | 🟢 Online | 1/2 |
| TVU Sucre | Universitário | Chuquisaca | 🟢 Online | 1/1 |
| UMSA TVU Internacional | Universitário | La Paz | 🟢 Online | 2/2 |
| UMSA TVU La Paz | Universitário | La Paz | 🟢 Online | 4/4 |
| Unifranz TV | Universitário | — | 🔴 Offline | 0/3 |
| Unitel Cochabamba | Geral | Cochabamba | 🔴 Offline | 0/2 |
| Unitel La Paz | Geral | La Paz | 🔴 Offline | 0/2 |
| Unitel Santa Cruz | Geral | Santa Cruz | 🟢 Online | 1/2 |
| Univalle TV | Universitário | Cochabamba | 🟢 Online | 2/2 |
| UPEA TV | Universitário | La Paz | 🟢 Online | 1/1 |
| Vos TV | Geral | — | 🟢 Online | 2/3 |
| VTV Canal 17 | Religioso | — | 🔴 Offline | 0/2 |
| Wara TV | Geral | — | 🔴 Offline | 0/1 |
| XTO TV | Geral | — | 🟢 Online | 1/2 |
| Zoy TV | Geral | — | 🔴 Offline | 0/1 |
| Zuraca TV | Negócios | — | 🟢 Online | 2/2 |

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
