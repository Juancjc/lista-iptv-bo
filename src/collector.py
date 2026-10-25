"""Coleta das playlists M3U configuradas em config/sources.json."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path

import aiohttp

from src.channels import M3UEntry, UnsafeURLError, check_url, extract_labels, parse_m3u

log = logging.getLogger(__name__)

MAX_SOURCE_BYTES = 5_000_000


@dataclass
class SourceReport:
    name: str
    location: str
    ok: bool = False
    from_cache: bool = False
    error: str | None = None
    entries: int = 0
    accepted: int = 0
    rejected: int = 0


@dataclass
class Rejection:
    source: str
    title: str
    url: str
    reason: str


@dataclass
class CollectionResult:
    entries: list[tuple[M3UEntry, bool]] = field(default_factory=list)
    reports: list[SourceReport] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)

    @property
    def failed_sources(self) -> set[str]:
        """Fontes cujo conteúdo atual não pôde ser obtido (nem mesmo via cache)."""
        return {r.name for r in self.reports if not r.ok}


class Collector:
    def __init__(self, config: dict, root: Path, cache_dir: Path | None = None):
        self.config = config
        self.root = root
        self.cache_dir = cache_dir or root / "data" / "cache" / "sources"
        rules = config.get("rules", {})
        self.exclude_labels = {lbl.lower() for lbl in rules.get("exclude_labels", [])}
        self.block_patterns = [p.lower() for p in rules.get("url_block_patterns", [])]
        vcfg = config.get("validator", {})
        self.timeout = aiohttp.ClientTimeout(total=vcfg.get("timeout_seconds", 15) * 2)
        self.user_agent = vcfg.get("user_agent", "lista-iptv-bo")

    async def collect(self) -> CollectionResult:
        sources = [s for s in self.config.get("sources", []) if s.get("enabled", True)]
        # fontes com tvg-id confiável primeiro, para que as demais possam ser casadas pelo nome
        sources.sort(key=lambda s: not s.get("use_tvg_id", True))
        result = CollectionResult()
        async with aiohttp.ClientSession(timeout=self.timeout,
                                         headers={"User-Agent": self.user_agent}) as session:
            texts = await asyncio.gather(*(self._load(session, s) for s in sources))
        for source, (report, text) in zip(sources, texts):
            result.reports.append(report)
            if text is None:
                continue
            entries = parse_m3u(text, source=source["name"])
            report.entries = len(entries)
            for entry in entries:
                reason = self.reject_reason(entry, source)
                if reason:
                    report.rejected += 1
                    result.rejections.append(Rejection(source["name"], entry.title, entry.url, reason))
                else:
                    report.accepted += 1
                    result.entries.append((entry, bool(source.get("use_tvg_id", True))))
            log.info("Fonte %-22s %4d entradas, %4d aceitas, %4d rejeitadas%s",
                     source["name"], report.entries, report.accepted, report.rejected,
                     " (cache)" if report.from_cache else "")
        return result

    async def _load(self, session: aiohttp.ClientSession, source: dict) -> tuple[SourceReport, str | None]:
        name = source["name"]
        if "path" in source:
            report = SourceReport(name=name, location=source["path"])
            path = self.root / source["path"]
            try:
                text = path.read_text(encoding="utf-8")
                report.ok = True
                return report, text
            except OSError as exc:
                report.error = f"arquivo local indisponível: {exc}"
                log.error("Fonte %s: %s", name, report.error)
                return report, None

        url = source["url"]
        report = SourceReport(name=name, location=url)
        try:
            check_url(url)
            async with session.get(url) as resp:
                if resp.status != 200:
                    raise aiohttp.ClientResponseError(resp.request_info, resp.history,
                                                      status=resp.status, message=resp.reason or "")
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.content.iter_chunked(65536):
                    chunks.append(chunk)
                    total += len(chunk)
                    if total > MAX_SOURCE_BYTES:
                        raise ValueError("playlist de origem grande demais")
                text = b"".join(chunks).decode("utf-8", errors="replace")
            if "#EXTINF" not in text:
                raise ValueError("conteúdo não parece uma playlist M3U")
            report.ok = True
            self._write_cache(name, text)
            return report, text
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, UnsafeURLError) as exc:
            report.error = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
            log.error("Fonte %s inacessível: %s", name, report.error)
            cached = self._read_cache(name)
            if cached is not None:
                # o conteúdo veio do cache: usamos para coletar, mas a fonte continua marcada
                # como falha para que streams dela não sejam descartados por ausência
                log.warning("Fonte %s: usando cópia em cache", name)
                report.from_cache = True
                return report, cached
            return report, None

    def reject_reason(self, entry: M3UEntry, source: dict) -> str | None:
        include_groups = source.get("include_groups")
        if include_groups and entry.group not in include_groups:
            return f"grupo fora do escopo: {entry.group or '(vazio)'}"
        suffix = source.get("require_tvg_id_suffix")
        if suffix and not entry.tvg_id.split("@", 1)[0].lower().endswith(suffix.lower()):
            return f"canal não boliviano (tvg-id: {entry.tvg_id or '(vazio)'})"
        _, labels = extract_labels(entry.title)
        blocked = [lbl for lbl in labels if lbl.lower() in self.exclude_labels]
        if blocked:
            return f"rótulo excluído: {', '.join(blocked)}"
        lowered = entry.url.lower()
        for pattern in self.block_patterns:
            if pattern in lowered:
                return f"URL bloqueada pela regra '{pattern}' (token/DRM/página/operadora)"
        try:
            check_url(entry.url)
        except UnsafeURLError as exc:
            return f"URL inválida: {exc}"
        return None

    def _write_cache(self, name: str, text: str) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            (self.cache_dir / f"{name}.m3u").write_text(text, encoding="utf-8", newline="")
        except OSError as exc:
            log.warning("Não foi possível gravar cache da fonte %s: %s", name, exc)

    def _read_cache(self, name: str) -> str | None:
        path = self.cache_dir / f"{name}.m3u"
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
