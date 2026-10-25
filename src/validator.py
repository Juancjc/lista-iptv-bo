"""Verificação assíncrona de streams: HTTP, estrutura da playlist HLS e segmentos de mídia."""

from __future__ import annotations

import asyncio
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urljoin

import aiohttp

from src.channels import (
    ERROR_PERMANENT,
    ERROR_TRANSIENT,
    STATUS_OFFLINE,
    STATUS_ONLINE,
    Stream,
    UnsafeURLError,
    check_url,
)

log = logging.getLogger(__name__)

_ATTR_RE = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')
_DRM_KEYFORMATS = ("widevine", "playready", "com.apple.streamingkeydelivery", "edef8ba9", "9a04f079")
_FMP4_BOXES = {b"ftyp", b"styp", b"moof", b"sidx", b"moov", b"emsg", b"prft"}


class CheckFailed(Exception):
    def __init__(self, message: str, kind: str = ERROR_PERMANENT, http_status: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.http_status = http_status


@dataclass
class Variant:
    url: str
    bandwidth: int = 0
    resolution: str | None = None


@dataclass
class PlaylistInfo:
    kind: str  # "master" | "media"
    variants: list[Variant] = field(default_factory=list)
    segments: list[str] = field(default_factory=list)
    init_segment: str | None = None
    target_duration: float | None = None
    encrypted: bool = False
    drm: bool = False
    endlist: bool = False


@dataclass
class CheckResult:
    ok: bool
    error: str | None = None
    error_kind: str | None = None
    http_status: int | None = None
    stream_type: str | None = None
    resolution: str | None = None
    bandwidth: int | None = None
    segment_checked: bool = False
    response_ms: int | None = None


# ---------------------------------------------------------------------------
# Análise de conteúdo (funções puras, testáveis sem rede)
# ---------------------------------------------------------------------------


def parse_attributes(text: str) -> dict[str, str]:
    return {k: v.strip('"') for k, v in _ATTR_RE.findall(text)}


def analyze_playlist(text: str, base_url: str) -> PlaylistInfo:
    """Valida a estrutura de uma playlist HLS. Lança CheckFailed se for inválida."""
    lines = [ln.strip() for ln in text.lstrip("﻿").splitlines() if ln.strip()]
    if not lines or not lines[0].startswith("#EXTM3U"):
        raise CheckFailed("playlist HLS inválida: não começa com #EXTM3U")

    variants: list[Variant] = []
    segments: list[str] = []
    info = PlaylistInfo(kind="media")
    pending_variant: dict[str, str] | None = None
    pending_segment = False

    for line in lines[1:]:
        if line.startswith("#EXT-X-STREAM-INF:"):
            pending_variant = parse_attributes(line.split(":", 1)[1])
        elif line.startswith("#EXTINF:"):
            pending_segment = True
        elif line.startswith("#EXT-X-TARGETDURATION:"):
            try:
                info.target_duration = float(line.split(":", 1)[1])
            except ValueError:
                raise CheckFailed("playlist HLS inválida: EXT-X-TARGETDURATION malformado")
        elif line.startswith(("#EXT-X-KEY:", "#EXT-X-SESSION-KEY:")):
            attrs = parse_attributes(line.split(":", 1)[1])
            method = attrs.get("METHOD", "NONE").upper()
            keyformat = attrs.get("KEYFORMAT", "").lower()
            if method != "NONE":
                info.encrypted = True
            if method.startswith("SAMPLE-AES") or any(k in keyformat for k in _DRM_KEYFORMATS):
                info.drm = True
        elif line.startswith("#EXT-X-MAP:"):
            uri = parse_attributes(line.split(":", 1)[1]).get("URI")
            if uri:
                info.init_segment = urljoin(base_url, uri)
        elif line.startswith("#EXT-X-ENDLIST"):
            info.endlist = True
        elif line.startswith("#"):
            continue
        else:
            if pending_variant is not None:
                try:
                    bandwidth = int(pending_variant.get("BANDWIDTH", "0") or 0)
                except ValueError:
                    bandwidth = 0
                variants.append(Variant(urljoin(base_url, line), bandwidth,
                                        pending_variant.get("RESOLUTION")))
                pending_variant = None
            elif pending_segment:
                segments.append(urljoin(base_url, line))
                pending_segment = False

    if info.drm:
        raise CheckFailed("stream protegido por DRM (não suportado)")
    if variants:
        info.kind = "master"
        info.variants = variants
        return info
    if not segments:
        raise CheckFailed("playlist HLS inválida: sem segmentos (#EXTINF) nem variantes")
    if info.target_duration is None:
        raise CheckFailed("playlist HLS inválida: falta EXT-X-TARGETDURATION")
    info.segments = segments
    return info


def looks_like_html(data: bytes) -> bool:
    head = data[:512].lstrip().lower()
    return head.startswith((b"<!doctype html", b"<html", b"<head", b"<body")) or b"<html" in head


def is_mpeg_ts(data: bytes) -> bool:
    if len(data) < 188 or data[0] != 0x47:
        return False
    return len(data) < 376 or data[188] == 0x47


def sniff_media(data: bytes) -> str | None:
    """Identifica o tipo de um segmento de mídia pelos primeiros bytes."""
    if not data:
        return None
    if is_mpeg_ts(data):
        return "ts"
    if len(data) >= 8 and data[4:8] in _FMP4_BOXES:
        return "fmp4"
    if data.startswith(b"ID3"):
        return "id3"
    if len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xF0) == 0xF0:
        return "aac"
    return None


def check_dash(text: str) -> None:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise CheckFailed(f"manifesto DASH inválido: {exc}")
    if not root.tag.endswith("MPD"):
        raise CheckFailed("manifesto DASH inválido: raiz não é MPD")
    if any(el.tag.endswith("ContentProtection") for el in root.iter()):
        raise CheckFailed("stream protegido por DRM (não suportado)")
    if not any(el.tag.endswith("AdaptationSet") for el in root.iter()):
        raise CheckFailed("manifesto DASH inválido: sem AdaptationSet")


def classify_status(status: int) -> str:
    return ERROR_TRANSIENT if status >= 500 or status in (408, 425, 429) else ERROR_PERMANENT


def apply_result(stream: Stream, result: CheckResult, now: str) -> None:
    stream.last_checked = now
    stream.http_status = result.http_status
    stream.response_ms = result.response_ms
    stream.segment_checked = result.segment_checked
    if result.stream_type:
        stream.stream_type = result.stream_type
    if result.ok:
        stream.status = STATUS_ONLINE
        stream.error = None
        stream.error_kind = None
        stream.resolution = result.resolution or stream.resolution
        stream.bandwidth = result.bandwidth or stream.bandwidth
        stream.last_success = now
        stream.consecutive_failures = 0
    else:
        stream.status = STATUS_OFFLINE
        stream.error = result.error
        stream.error_kind = result.error_kind
        stream.consecutive_failures += 1


# ---------------------------------------------------------------------------
# Validador com rede
# ---------------------------------------------------------------------------


class Validator:
    def __init__(self, config: dict, allow_private: bool = False):
        self.concurrency = int(config.get("concurrency", 12))
        self.per_host = int(config.get("per_host_limit", 3))
        self.timeout = float(config.get("timeout_seconds", 15))
        self.retries = int(config.get("retries", 1))
        self.max_playlist = int(config.get("max_playlist_bytes", 2_000_000))
        self.probe_bytes = int(config.get("segment_probe_bytes", 65536))
        self.user_agent = config.get("user_agent", "VLC/3.0.20 LibVLC/3.0.20")
        self.allow_private = allow_private
        self._cache: dict[tuple, CheckResult] = {}

    async def validate_all(self, streams: list[Stream]) -> None:
        """Verifica todos os streams em paralelo (com limite) e atualiza o estado de cada um."""
        if not streams:
            return
        sem = asyncio.Semaphore(self.concurrency)
        connector = aiohttp.TCPConnector(limit=self.concurrency * 2, limit_per_host=self.per_host)
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=self.timeout, sock_read=self.timeout)
        done = 0
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            async def worker(stream: Stream) -> None:
                nonlocal done
                async with sem:
                    result = await self.check_with_retry(session, stream)
                now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                apply_result(stream, result, now)
                done += 1
                if result.ok:
                    log.info("[%3d/%d] OK    %s (%s%s)", done, len(streams), stream.url,
                             result.stream_type, f", {result.resolution}" if result.resolution else "")
                else:
                    log.info("[%3d/%d] FALHA %s — %s", done, len(streams), stream.url, result.error)

            await asyncio.gather(*(worker(s) for s in streams))

    async def check_with_retry(self, session: aiohttp.ClientSession, stream: Stream) -> CheckResult:
        key = (stream.url, stream.user_agent, stream.referrer)
        if key in self._cache:
            return self._cache[key]
        result = CheckResult(ok=False, error="não verificado")
        for attempt in range(self.retries + 1):
            try:
                result = await asyncio.wait_for(self.check(session, stream), timeout=self.timeout * 4)
            except asyncio.TimeoutError:
                result = CheckResult(ok=False, error="tempo esgotado na verificação",
                                     error_kind=ERROR_TRANSIENT)
            except Exception as exc:  # proteção final: um stream nunca derruba a execução
                log.exception("Erro inesperado ao verificar %s", stream.url)
                result = CheckResult(ok=False, error=f"erro inesperado: {type(exc).__name__}",
                                     error_kind=ERROR_TRANSIENT)
            if result.ok or result.error_kind != ERROR_TRANSIENT:
                break
            if attempt < self.retries:
                await asyncio.sleep(1.5 * (attempt + 1))
        self._cache[key] = result
        return result

    def _headers(self, stream: Stream) -> dict[str, str]:
        headers = {"User-Agent": stream.user_agent or self.user_agent, "Accept": "*/*"}
        if stream.referrer:
            headers["Referer"] = stream.referrer
        return headers

    async def check(self, session: aiohttp.ClientSession, stream: Stream) -> CheckResult:
        headers = self._headers(stream)
        started = time.monotonic()
        try:
            check_url(stream.url, self.allow_private)
            status, final_url, data, ctype = await self._fetch(session, stream.url, headers, self.max_playlist,
                                                              sniff_binary=True)
            elapsed = int((time.monotonic() - started) * 1000)
            result = await self._inspect(session, headers, final_url, data, ctype)
            result.http_status = status
            result.response_ms = elapsed
            return result
        except UnsafeURLError as exc:
            return CheckResult(ok=False, error=f"URL rejeitada: {exc}", error_kind=ERROR_PERMANENT)
        except CheckFailed as exc:
            return CheckResult(ok=False, error=str(exc), error_kind=exc.kind, http_status=exc.http_status,
                               response_ms=int((time.monotonic() - started) * 1000))
        except aiohttp.ClientSSLError as exc:
            return CheckResult(ok=False, error=f"erro TLS/certificado: {exc.__class__.__name__}",
                               error_kind=ERROR_PERMANENT)
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            msg = str(exc) or exc.__class__.__name__
            return CheckResult(ok=False, error=f"falha de rede: {msg[:200]}", error_kind=ERROR_TRANSIENT)

    async def _fetch(self, session, url, headers, limit, sniff_binary=False, range_bytes=None):
        """GET com limite de bytes. Para streams binários contínuos (TS) lê só o início."""
        req_headers = dict(headers)
        if range_bytes:
            req_headers["Range"] = f"bytes=0-{range_bytes - 1}"
        async with session.get(url, headers=req_headers, allow_redirects=True, max_redirects=5) as resp:
            if resp.status not in (200, 206):
                raise CheckFailed(f"HTTP {resp.status}", classify_status(resp.status), resp.status)
            final_url = str(resp.url)
            check_url(final_url, self.allow_private)
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = await resp.content.read(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if sniff_binary and total >= 1024 and is_mpeg_ts(b"".join(chunks)[:1024]):
                    break  # transmissão TS contínua: o início basta
                if range_bytes and total >= range_bytes:
                    break
                if total > limit:
                    raise CheckFailed("resposta grande demais para uma playlist")
            return resp.status, final_url, b"".join(chunks), resp.headers.get("Content-Type", "")

    async def _inspect(self, session, headers, url, data: bytes, ctype: str, depth: int = 0) -> CheckResult:
        if not data:
            raise CheckFailed("resposta vazia")
        if is_mpeg_ts(data):
            return CheckResult(ok=True, stream_type="ts", segment_checked=True)
        if looks_like_html(data):
            raise CheckFailed("a URL retorna uma página HTML, não um stream")
        text = data.decode("utf-8", errors="replace")
        stripped = text.lstrip("﻿ \r\n\t")
        if stripped.startswith("<?xml") or "<MPD" in stripped[:2000]:
            check_dash(stripped)
            return CheckResult(ok=True, stream_type="dash")
        if not stripped.startswith("#EXTM3U"):
            raise CheckFailed(f"conteúdo não reconhecido como stream ({ctype or 'sem Content-Type'})")

        info = analyze_playlist(stripped, url)
        if info.kind == "master":
            if depth > 1:
                raise CheckFailed("playlists master aninhadas demais")
            best = max(info.variants, key=lambda v: v.bandwidth)
            # testa a variante mais leve (menos tráfego); se falhar, tenta as demais
            ordered = sorted(info.variants, key=lambda v: v.bandwidth)
            last_error: CheckFailed | None = None
            for variant in ordered[:3]:
                try:
                    _, final, vdata, vctype = await self._fetch(session, variant.url, headers, self.max_playlist)
                    sub = await self._inspect(session, headers, final, vdata, vctype, depth + 1)
                    sub.resolution = best.resolution or sub.resolution
                    sub.bandwidth = best.bandwidth or sub.bandwidth
                    return sub
                except CheckFailed as exc:
                    last_error = exc
            assert last_error is not None
            raise CheckFailed(f"nenhuma variante funcional: {last_error}", last_error.kind,
                              last_error.http_status)

        await self._check_segment(session, headers, info)
        return CheckResult(ok=True, stream_type="hls", segment_checked=True)

    async def _check_segment(self, session, headers, info: PlaylistInfo) -> None:
        # o segmento mais recente é o que tem menos chance de já ter expirado no servidor
        segment = info.segments[-1]
        try:
            _, _, data, ctype = await self._fetch(session, segment, headers, self.probe_bytes * 4,
                                                  range_bytes=self.probe_bytes)
        except CheckFailed as exc:
            raise CheckFailed(f"segmento inacessível: {exc}", exc.kind, exc.http_status)
        if not data:
            raise CheckFailed("segmento vazio", ERROR_TRANSIENT)
        if looks_like_html(data):
            raise CheckFailed("segmento retorna HTML em vez de vídeo")
        if sniff_media(data) is None and not info.encrypted:
            ctype = ctype.lower()
            if not (ctype.startswith(("video/", "audio/")) or "mp2t" in ctype or "octet-stream" in ctype):
                raise CheckFailed("segmento não contém mídia reconhecível")
