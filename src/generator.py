"""Geração das playlists M3U, do JSON de dados e do README."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from string import Template

from src.channels import ERROR_TRANSIENT, STATUS_OFFLINE, STATUS_ONLINE, Channel, Stream, sort_channels

log = logging.getLogger(__name__)

PLAYLIST_MAIN = "bolivia.m3u"
PLAYLIST_ONLINE = "bolivia-online.m3u"
PLAYLIST_ALL = "bolivia-all.m3u"

# campos que mudam a cada execução sem representar mudança real nas listas
VOLATILE_KEYS = {"generated_at", "last_checked", "last_success", "response_ms", "consecutive_failures",
                 "error", "duration_seconds"}

_TYPE_RANK = {"hls": 0, "ts": 1, "dash": 2}


# ---------------------------------------------------------------------------
# Regras de seleção
# ---------------------------------------------------------------------------


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def is_usable(stream: Stream, grace_hours: float, now: datetime) -> bool:
    """Online agora, ou com falha temporária e sucesso recente (tolerância a instabilidades)."""
    if stream.status == STATUS_ONLINE:
        return True
    if stream.status == STATUS_OFFLINE and stream.error_kind == ERROR_TRANSIENT:
        last_ok = parse_time(stream.last_success)
        return last_ok is not None and now - last_ok <= timedelta(hours=grace_hours)
    return False


def _resolution_height(stream: Stream) -> int:
    try:
        return int((stream.resolution or "0x0").lower().split("x")[1])
    except (IndexError, ValueError):
        return 0


def stream_rank(stream: Stream) -> tuple:
    return (
        stream.status != STATUS_ONLINE,
        "manual" not in stream.sources,
        not stream.segment_checked,
        _TYPE_RANK.get(stream.stream_type or "", 3),
        -_resolution_height(stream),
        stream.response_ms if stream.response_ms is not None else 10**9,
    )


def ordered_streams(channel: Channel) -> list[Stream]:
    return sorted(channel.streams, key=stream_rank)


# ---------------------------------------------------------------------------
# M3U
# ---------------------------------------------------------------------------


def _attr(value: str) -> str:
    return value.replace('"', "'").replace("\r", " ").replace("\n", " ").strip()


def m3u_entry(channel: Channel, stream: Stream, display_name: str) -> str:
    attrs = [
        f'tvg-id="{_attr(channel.id)}"',
        f'tvg-name="{_attr(channel.name)}"',
        f'tvg-logo="{_attr(channel.logo)}"',
        f'group-title="{_attr(channel.group_title)}"',
    ]
    if stream.user_agent:
        attrs.append(f'http-user-agent="{_attr(stream.user_agent)}"')
    if stream.referrer:
        attrs.append(f'http-referrer="{_attr(stream.referrer)}"')
    lines = [f"#EXTINF:-1 {' '.join(attrs)},{display_name.replace(',', ' ').strip()}"]
    if stream.user_agent:
        lines.append(f"#EXTVLCOPT:http-user-agent={stream.user_agent}")
    if stream.referrer:
        lines.append(f"#EXTVLCOPT:http-referrer={stream.referrer}")
    lines.append(stream.url)
    return "\n".join(lines)


def render_playlist(items: list[tuple[Channel, Stream, str]]) -> str:
    body = [m3u_entry(c, s, name) for c, s, name in items]
    return "#EXTM3U\n" + "".join(entry + "\n" for entry in body)


def build_playlists(channels: list[Channel], grace_hours: float, now: datetime) -> dict[str, str]:
    main: list[tuple[Channel, Stream, str]] = []
    online: list[tuple[Channel, Stream, str]] = []
    every: list[tuple[Channel, Stream, str]] = []

    for channel in sort_channels(channels):
        streams = ordered_streams(channel)
        usable = [s for s in streams if is_usable(s, grace_hours, now)]
        if usable:
            main.append((channel, usable[0], channel.name))
        live = [s for s in streams if s.status == STATUS_ONLINE]
        for i, stream in enumerate(live):
            online.append((channel, stream, channel.name if i == 0 else f"{channel.name} (Alt. {i + 1})"))
        for i, stream in enumerate(streams):
            name = channel.name if i == 0 else f"{channel.name} (Alt. {i + 1})"
            if stream.status == STATUS_OFFLINE:
                name += " [Offline]"
            every.append((channel, stream, name))

    return {
        PLAYLIST_MAIN: render_playlist(main),
        PLAYLIST_ONLINE: render_playlist(online),
        PLAYLIST_ALL: render_playlist(every),
    }


# ---------------------------------------------------------------------------
# Estatísticas, JSON e README
# ---------------------------------------------------------------------------


@dataclass
class Stats:
    channels_total: int
    channels_main: int
    channels_online: int
    streams_total: int
    streams_online: int


def compute_stats(channels: list[Channel], grace_hours: float, now: datetime) -> Stats:
    streams = [s for c in channels for s in c.streams]
    return Stats(
        channels_total=len(channels),
        channels_main=sum(1 for c in channels if any(is_usable(s, grace_hours, now) for s in c.streams)),
        channels_online=sum(1 for c in channels if any(s.status == STATUS_ONLINE for s in c.streams)),
        streams_total=len(streams),
        streams_online=sum(1 for s in streams if s.status == STATUS_ONLINE),
    )


def build_data_document(channels: list[Channel], stats: Stats, sources: list[dict], now: datetime) -> dict:
    return {
        "generated_at": now.replace(microsecond=0).isoformat(),
        "stats": stats.__dict__,
        "sources": sources,
        "channels": [c.to_dict() for c in sort_channels(channels)],
    }


def strip_volatile(value):
    if isinstance(value, dict):
        return {k: strip_volatile(v) for k, v in value.items() if k not in VOLATILE_KEYS}
    if isinstance(value, list):
        return [strip_volatile(v) for v in value]
    return value


def has_material_change(old_doc: dict | None, new_doc: dict, heartbeat_hours: float, now: datetime) -> bool:
    """True se algo relevante mudou, ou se o último registro é mais antigo que o heartbeat."""
    if not old_doc:
        return True
    if strip_volatile(old_doc) != strip_volatile(new_doc):
        return True
    last = parse_time(old_doc.get("generated_at"))
    return last is None or now - last >= timedelta(hours=heartbeat_hours)


def repo_info(config: dict) -> tuple[str, str]:
    repo = os.environ.get("GITHUB_REPOSITORY") or config.get("repository", "SEU_USUARIO/lista-iptv-bo")
    branch = config.get("branch", "main")
    if os.environ.get("GITHUB_REF_TYPE") == "branch" and os.environ.get("GITHUB_REF_NAME"):
        branch = os.environ["GITHUB_REF_NAME"]
    return repo, branch


def _status_icon(channel: Channel, grace_hours: float, now: datetime) -> str:
    if any(s.status == STATUS_ONLINE for s in channel.streams):
        return "🟢 Online"
    if any(is_usable(s, grace_hours, now) for s in channel.streams):
        return "🟡 Instável"
    return "🔴 Offline"


def render_readme(template: str, channels: list[Channel], stats: Stats, sources: list[dict],
                  config: dict, grace_hours: float, now: datetime) -> str:
    repo, branch = repo_info(config)
    raw = f"https://raw.githubusercontent.com/{repo}/{branch}/playlists"
    rows = []
    for c in sort_channels(channels):
        online = sum(1 for s in c.streams if s.status == STATUS_ONLINE)
        rows.append(f"| {c.name} | {c.category} | {c.region or '—'} | {_status_icon(c, grace_hours, now)} "
                    f"| {online}/{len(c.streams)} |")
    source_rows = []
    for s in sources:
        state = "✅ OK" if s["ok"] else ("⚠️ Falhou (cache)" if s.get("from_cache") else "❌ Falhou")
        source_rows.append(f"| `{s['name']}` | {state} | {s['accepted']} | {s['rejected']} |")
    return Template(template).safe_substitute(
        repo=repo,
        branch=branch,
        raw_main=f"{raw}/{PLAYLIST_MAIN}",
        raw_online=f"{raw}/{PLAYLIST_ONLINE}",
        raw_all=f"{raw}/{PLAYLIST_ALL}",
        channels_total=stats.channels_total,
        channels_main=stats.channels_main,
        channels_online=stats.channels_online,
        streams_total=stats.streams_total,
        streams_online=stats.streams_online,
        updated_at=now.astimezone(timezone(timedelta(hours=-4))).strftime("%d/%m/%Y %H:%M") + " (horário da Bolívia, UTC−4)",
        channel_table="\n".join(rows),
        source_table="\n".join(source_rows),
    )


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def write_json(path: Path, data: dict) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
