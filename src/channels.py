"""Modelos de dados, parser M3U, normalização e catálogo de canais bolivianos."""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable
from urllib.parse import urlsplit, urlunsplit

# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------

STATUS_ONLINE = "online"
STATUS_OFFLINE = "offline"
STATUS_UNCHECKED = "unchecked"

ERROR_TRANSIENT = "transient"  # timeout, 5xx, falha de rede: pode voltar sozinho
ERROR_PERMANENT = "permanent"  # 404, playlist inválida, página HTML, DRM


@dataclass
class Stream:
    url: str
    sources: list[str] = field(default_factory=list)
    title: str = ""
    user_agent: str | None = None
    referrer: str | None = None
    labels: list[str] = field(default_factory=list)
    status: str = STATUS_UNCHECKED
    error: str | None = None
    error_kind: str | None = None
    http_status: int | None = None
    stream_type: str | None = None
    resolution: str | None = None
    bandwidth: int | None = None
    segment_checked: bool = False
    response_ms: int | None = None
    first_seen: str | None = None
    last_checked: str | None = None
    last_success: str | None = None
    consecutive_failures: int = 0

    @classmethod
    def from_dict(cls, data: dict) -> "Stream":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Channel:
    id: str
    name: str
    logo: str = ""
    category: str = "Geral"
    region: str = ""
    streams: list[Stream] = field(default_factory=list)

    @property
    def group_title(self) -> str:
        return f"Bolívia | {self.category}"

    def find_stream(self, url: str) -> Stream | None:
        key = url_key(url)
        return next((s for s in self.streams if url_key(s.url) == key), None)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Channel":
        streams = [Stream.from_dict(s) for s in data.get("streams", [])]
        return cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            logo=data.get("logo", ""),
            category=data.get("category", "Geral"),
            region=data.get("region", ""),
            streams=streams,
        )


@dataclass
class M3UEntry:
    """Uma entrada bruta lida de uma playlist M3U."""

    title: str
    url: str
    attrs: dict[str, str] = field(default_factory=dict)
    user_agent: str | None = None
    referrer: str | None = None
    source: str = ""

    @property
    def tvg_id(self) -> str:
        return self.attrs.get("tvg-id", "").strip()

    @property
    def logo(self) -> str:
        return self.attrs.get("tvg-logo", "").strip()

    @property
    def group(self) -> str:
        return self.attrs.get("group-title", "").strip()


# ---------------------------------------------------------------------------
# Parser M3U
# ---------------------------------------------------------------------------

_ATTR_RE = re.compile(r'([A-Za-z0-9_-]+)="([^"]*)"')


def _split_extinf(line: str) -> tuple[str, str]:
    """Separa '#EXTINF:-1 attrs,Título' em (attrs, título) respeitando aspas."""
    body = line.split(":", 1)[1] if ":" in line else ""
    in_quotes = False
    for i, ch in enumerate(body):
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == "," and not in_quotes:
            return body[:i], body[i + 1 :].strip()
    return body, ""


def parse_m3u(text: str, source: str = "") -> list[M3UEntry]:
    """Converte o texto de uma playlist M3U em entradas. Linhas inválidas são ignoradas."""
    entries: list[M3UEntry] = []
    current: M3UEntry | None = None
    for raw in text.lstrip("﻿").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.upper().startswith("#EXTINF"):
            attrs_part, title = _split_extinf(line)
            attrs = {k.lower(): v for k, v in _ATTR_RE.findall(attrs_part)}
            current = M3UEntry(title=title, url="", attrs=attrs, source=source)
            current.user_agent = attrs.get("http-user-agent") or None
            current.referrer = attrs.get("http-referrer") or attrs.get("http-referer") or None
        elif line.upper().startswith("#EXTVLCOPT:") and current is not None:
            opt = line.split(":", 1)[1]
            key, _, value = opt.partition("=")
            key = key.strip().lower()
            if key == "http-user-agent":
                current.user_agent = value.strip() or None
            elif key in ("http-referrer", "http-referer"):
                current.referrer = value.strip() or None
        elif line.startswith("#"):
            continue
        elif current is not None:
            current.url = line
            entries.append(current)
            current = None
    return entries


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

MAX_URL_LENGTH = 2048


class UnsafeURLError(ValueError):
    pass


def check_url(url: str, allow_private: bool = False) -> str:
    """Valida e devolve a URL normalizada; lança UnsafeURLError se for malformada/insegura."""
    if not url or len(url) > MAX_URL_LENGTH:
        raise UnsafeURLError("URL vazia ou longa demais")
    if any(ord(c) < 33 or ord(c) == 127 for c in url):
        raise UnsafeURLError("URL contém espaços ou caracteres de controle")
    try:
        parts = urlsplit(url)
        port = parts.port  # valida a porta
    except ValueError as exc:
        raise UnsafeURLError(f"URL malformada: {exc}") from exc
    if parts.scheme.lower() not in ("http", "https"):
        raise UnsafeURLError(f"esquema não suportado: {parts.scheme or '(nenhum)'}")
    host = parts.hostname
    if not host:
        raise UnsafeURLError("URL sem host")
    if parts.username or parts.password:
        raise UnsafeURLError("URL com credenciais embutidas")
    if port == 0:
        raise UnsafeURLError("porta inválida")
    if not allow_private:
        if host == "localhost" or host.endswith(".local") or host.endswith(".localhost"):
            raise UnsafeURLError("host local não permitido")
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            ip = None
        if ip is not None and (ip.is_private or ip.is_loopback or ip.is_link_local
                               or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
            raise UnsafeURLError("endereço IP privado/reservado não permitido")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, parts.fragment))


def url_key(url: str) -> str:
    """Chave de deduplicação de URL (esquema/host em minúsculas, sem fragmento)."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))


# ---------------------------------------------------------------------------
# Normalização de nomes e identificadores
# ---------------------------------------------------------------------------

_QUALITY_RE = re.compile(r"\((\d{3,4}p|4k)\)", re.IGNORECASE)
_LABEL_RE = re.compile(r"\[([^\]]+)\]")
_NOISE_WORDS = {"hd", "fhd", "sd", "uhd", "4k", "bo", "en", "vivo"}


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def extract_labels(title: str) -> tuple[str, list[str]]:
    """Remove '(720p)' e '[Not 24/7]' do título, devolvendo (título limpo, rótulos)."""
    labels = [m.strip() for m in _LABEL_RE.findall(title)]
    clean = _LABEL_RE.sub("", title)
    clean = _QUALITY_RE.sub("", clean)
    return re.sub(r"\s+", " ", clean).strip(), labels


def name_key(name: str) -> str:
    """Chave para comparar nomes de canais ('RED UNO LPZ HD' -> 'red uno lpz')."""
    clean, _ = extract_labels(name)
    clean = re.sub(r"\(bolivia\)", "", clean, flags=re.IGNORECASE)
    clean = strip_accents(clean).lower()
    words = re.split(r"[^a-z0-9.]+", clean)
    words = [w.strip(".") for w in words if w.strip(".") and w.strip(".") not in _NOISE_WORDS]
    return " ".join(words)


_ACRONYMS = {"TV", "ATB", "PAT", "RTP", "CTV", "UPEA", "TVU", "UMSA", "CCTV", "DTV", "PTV", "FTV", "XTO",
             "LPZ", "SCZ", "CBBA", "LP", "TDT", "CEACOM", "VTV", "SPC", "TLT", "FAP"}
_ROMAN_RE = re.compile(r"^[IVXLC]+$")


def pretty_name(title: str) -> str:
    """Nome de exibição: sem '(720p)', '[...]' e sufixos HD/SD; 'ZOY TV HD' -> 'Zoy TV'."""
    clean, _ = extract_labels(title)
    words = re.sub(r"\(bolivia\)", "", clean, flags=re.IGNORECASE).split()
    while len(words) > 1 and words[-1].upper() in ("HD", "FHD", "SD", "UHD"):
        words.pop()
    if clean.upper() == clean:
        words = [w if w in _ACRONYMS or _ROMAN_RE.match(w) or any(ch.isdigit() for ch in w)
                 else w.capitalize() for w in words]
    return " ".join(words)


def slug_id(name: str) -> str:
    """Gera um identificador estilo iptv-org a partir do nome ('Zoy TV HD' -> 'ZoyTV.bo')."""
    words = re.findall(r"[A-Za-z0-9]+", strip_accents(pretty_name(name)))
    base = "".join(w if w.isupper() else w[:1].upper() + w[1:] for w in words) or "Canal"
    return f"{base}.bo"


_GENERIC_FEEDS = {"sd", "hd", "fhd"}


def normalize_tvg_id(tvg_id: str) -> str:
    """'Bolivision.bo@SD' -> 'Bolivision.bo'; mantém feeds regionais ('RedUno.bo@LaPaz')."""
    tvg_id = tvg_id.strip()
    if not tvg_id:
        return ""
    base, _, feed = tvg_id.partition("@")
    if feed and feed.lower() not in _GENERIC_FEEDS:
        canonical = f"{base}@{feed}"
    else:
        canonical = base
    return ID_ALIASES.get(canonical, canonical)


# ---------------------------------------------------------------------------
# Catálogo de canais bolivianos (metadados e apelidos para casar nomes)
# ---------------------------------------------------------------------------

# id -> (nome de exibição, categoria, departamento)
CATALOG: dict[str, tuple[str, str, str]] = {
    "BoliviaTV.bo": ("Bolivia TV", "TV Pública", "La Paz"),
    "BoliviaTV72.bo": ("Bolivia TV 7.2", "TV Pública", "La Paz"),
    "Unitel.bo@SantaCruz": ("Unitel Santa Cruz", "Geral", "Santa Cruz"),
    "UnitelLaPaz.bo": ("Unitel La Paz", "Geral", "La Paz"),
    "UnitelCochabamba.bo": ("Unitel Cochabamba", "Geral", "Cochabamba"),
    "RedUno.bo": ("Red Uno", "Geral", ""),
    "RedUno.bo@LaPaz": ("Red Uno La Paz", "Geral", "La Paz"),
    "RedUno.bo@SantaCruz": ("Red Uno Santa Cruz", "Geral", "Santa Cruz"),
    "RedUno.bo@Cochabamba": ("Red Uno Cochabamba", "Geral", "Cochabamba"),
    "ATBLaPaz.bo": ("ATB", "Geral", "La Paz"),
    "Bolivision.bo": ("Bolivisión", "Geral", "La Paz"),
    "BolivisionSantaCruz.bo": ("Bolivisión Santa Cruz", "Geral", "Santa Cruz"),
    "PAT.bo@SantaCruz": ("PAT Santa Cruz", "Geral", "Santa Cruz"),
    "PATLaPaz.bo": ("PAT La Paz", "Geral", "La Paz"),
    "RTP.bo": ("RTP", "Geral", "La Paz"),
    "CadenaA.bo": ("Cadena A", "Notícias", "La Paz"),
    "AbyaYalaTV.bo": ("Abya Yala TV", "Geral", "La Paz"),
    "Gigavision.bo": ("Gigavisión", "Geral", ""),
    "Gigavision.bo@LaPaz": ("Gigavisión La Paz", "Geral", "La Paz"),
    "Gigavision.bo@SantaCruz": ("Gigavisión Santa Cruz", "Geral", "Santa Cruz"),
    "FidesTV.bo": ("Fides TV", "Notícias", "La Paz"),
    "ELDEBER.bo": ("El Deber TV", "Notícias", "Santa Cruz"),
    "UMSATVULP.bo": ("UMSA TVU La Paz", "Universitário", "La Paz"),
    "UMSATVUInternacional.bo": ("UMSA TVU Internacional", "Universitário", "La Paz"),
    "RadioUniversitariaSanAndres.bo": ("Radio Universitaria San Andrés", "Universitário", "La Paz"),
    "UnivalleTelevision.bo": ("Univalle TV", "Universitário", "Cochabamba"),
    "Unifranz.bo": ("Unifranz TV", "Universitário", ""),
    "UPEATV.bo": ("UPEA TV", "Universitário", "La Paz"),
    "TVUSucre.bo": ("TVU Sucre", "Universitário", "Chuquisaca"),
    "TVCulturas.bo": ("TV Culturas", "Cultural", ""),
    "CTV.bo": ("CTV Bolivia", "Geral", ""),
    "PTV.bo": ("PTV Paceñísima", "Geral", "La Paz"),
    "RedADvenirTV.bo": ("Red ADvenir TV", "Religioso", ""),
    "VTVCanal17.bo": ("VTV Canal 17", "Religioso", ""),
    "TLEstrella.bo": ("Tele Estrella", "Geral", ""),
    "XTOTV.bo": ("XTO TV", "Geral", ""),
    "CEACOMTV.bo": ("CEACOM TV", "Geral", ""),
    "F10HD.bo": ("F10", "Geral", ""),
}

_REGION_SUFFIX_RE = re.compile(r"(LaPaz|SantaCruz|Cochabamba|Tarija|Oruro|Potosi|Sucre|Beni|Pando)$")

# ids diferentes usados pelas fontes para o mesmo canal
ID_ALIASES: dict[str, str] = {
    "RedUnoSantaCruz.bo": "RedUno.bo@SantaCruz",
    "UnitelSantaCruz.bo": "Unitel.bo@SantaCruz",
}

# chave de nome (ver name_key) -> id
NAME_ALIASES: dict[str, str] = {
    "bolivia tv": "BoliviaTV.bo",
    "btv": "BoliviaTV.bo",
    "btv 7.1": "BoliviaTV.bo",
    "bolivia tv 7.1": "BoliviaTV.bo",
    "btv 7.2": "BoliviaTV72.bo",
    "bolivia tv 7.2": "BoliviaTV72.bo",
    "unitel": "Unitel.bo@SantaCruz",
    "unitel scz": "Unitel.bo@SantaCruz",
    "unitel lp": "UnitelLaPaz.bo",
    "unitel lpz": "UnitelLaPaz.bo",
    "red uno lpz": "RedUno.bo@LaPaz",
    "red uno lp": "RedUno.bo@LaPaz",
    "red uno scz": "RedUno.bo@SantaCruz",
    "red uno cbba": "RedUno.bo@Cochabamba",
    "atb": "ATBLaPaz.bo",
    "atb bolivia": "ATBLaPaz.bo",
    "atb movil": "ATBLaPaz.bo",
    "bolivision lpz": "Bolivision.bo",
    "bolivision scz": "BolivisionSantaCruz.bo",
    "upp tv bolivision scz": "BolivisionSantaCruz.bo",
    "rtp la paz": "RTP.bo",
    "tvu umsa": "UMSATVULP.bo",
    "universidadmayordesanandres": "UMSATVULP.bo",
    "pat santa cruz": "PAT.bo@SantaCruz",
    "red advenir": "RedADvenirTV.bo",
    "vtv tv": "VTVCanal17.bo",
    "univalle tv": "UnivalleTelevision.bo",
    "tele estrella tv": "TLEstrella.bo",
    "red gigavision lpz": "Gigavision.bo@LaPaz",
    "red gigavision scz": "Gigavision.bo@SantaCruz",
    "pacenisima tv": "PTV.bo",
    "ctv tv": "CTV.bo",
    "xto": "XTOTV.bo",
    "ceacom": "CEACOMTV.bo",
    "unifranz tv": "Unifranz.bo",
    "fides tv": "FidesTV.bo",
    "el deber tv": "ELDEBER.bo",
}

# categorias iptv-org (group-title) -> categoria em português
CATEGORY_MAP: dict[str, str] = {
    "general": "Geral",
    "news": "Notícias",
    "religious": "Religioso",
    "education": "Educativo",
    "culture": "Cultural",
    "music": "Música",
    "sports": "Esportes",
    "entertainment": "Entretenimento",
    "documentary": "Documentários",
    "shop": "Compras",
    "business": "Negócios",
    "travel": "Viagens",
    "kids": "Infantil",
    "animation": "Infantil",
    "lifestyle": "Estilo de Vida",
    "movies": "Filmes",
    "series": "Séries",
    "comedy": "Comédia",
    "science": "Ciência",
    "legislative": "Legislativo",
}


def map_category(group_title: str) -> str:
    """'Culture;Education;News' -> 'Cultural' (primeira categoria conhecida)."""
    for part in re.split(r"[;|,]", group_title or ""):
        mapped = CATEGORY_MAP.get(part.strip().lower())
        if mapped:
            return mapped
    return "Geral"


# ---------------------------------------------------------------------------
# Consolidação (deduplicação) das entradas coletadas
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def resolve_channel_id(entry: M3UEntry, use_tvg_id: bool, name_index: dict[str, str]) -> str:
    if use_tvg_id and entry.tvg_id:
        return normalize_tvg_id(entry.tvg_id)
    key = name_key(entry.title)
    if key in NAME_ALIASES:
        return NAME_ALIASES[key]
    if key in name_index:
        return name_index[key]
    return slug_id(entry.title)


def build_channels(entries: Iterable[tuple[M3UEntry, bool]], now: str | None = None) -> dict[str, Channel]:
    """Agrupa entradas por canal, deduplicando URLs e preservando URLs alternativas.

    `entries` é uma sequência de (entrada, usar_tvg_id). Entradas com tvg-id confiável
    devem vir primeiro para que as demais possam ser casadas pelo nome.
    """
    now = now or _now_iso()
    channels: dict[str, Channel] = {}
    name_index: dict[str, str] = {}

    for entry, use_tvg_id in entries:
        cid = resolve_channel_id(entry, use_tvg_id, name_index)
        title, labels = extract_labels(entry.title)
        channel = channels.get(cid)
        if channel is None:
            name, category, region = CATALOG.get(cid, (pretty_name(entry.title) or cid,
                                                       map_category(entry.group), ""))
            channel = Channel(id=cid, name=name, category=category, region=region)
            channels[cid] = channel
        if not channel.logo and entry.logo.startswith(("http://", "https://")):
            channel.logo = entry.logo
        name_index.setdefault(name_key(title), cid)
        name_index.setdefault(name_key(channel.name), cid)

        stream = channel.find_stream(entry.url)
        if stream is None:
            stream = Stream(url=entry.url, title=entry.title, first_seen=now)
            channel.streams.append(stream)
        if entry.source and entry.source not in stream.sources:
            stream.sources.append(entry.source)
        for label in labels:
            if label not in stream.labels:
                stream.labels.append(label)
        stream.user_agent = stream.user_agent or entry.user_agent
        stream.referrer = stream.referrer or entry.referrer
    fill_family_logos(channels)
    return channels


def brand_of(channel_id: str) -> str:
    """'UnitelLaPaz.bo' e 'Unitel.bo@SantaCruz' -> 'Unitel' (para compartilhar logos)."""
    base = channel_id.split("@", 1)[0].removesuffix(".bo")
    return _REGION_SUFFIX_RE.sub("", base) or base


def fill_family_logos(channels: dict[str, Channel]) -> None:
    """Canais regionais sem logo herdam o logo de outra praça da mesma emissora."""
    logos: dict[str, str] = {}
    for cid in sorted(channels):
        if channels[cid].logo:
            logos.setdefault(brand_of(cid), channels[cid].logo)
    for cid, channel in channels.items():
        if not channel.logo:
            channel.logo = logos.get(brand_of(cid), "")


def merge_with_previous(
    collected: dict[str, Channel],
    previous: dict[str, Channel],
    failed_sources: set[str],
    retention_days: int,
    now: datetime | None = None,
) -> dict[str, Channel]:
    """Combina o resultado da coleta atual com o estado anterior.

    - Histórico de verificação dos streams é preservado.
    - Streams cuja fonte falhou nesta execução são mantidos (falha temporária da fonte).
    - Streams removidos das fontes são mantidos por `retention_days` desde o último sucesso.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=retention_days)
    merged = dict(collected)

    for cid, old_channel in previous.items():
        channel = merged.get(cid)
        if channel is None:
            channel = Channel(id=old_channel.id, name=old_channel.name, logo=old_channel.logo,
                              category=old_channel.category, region=old_channel.region)
        elif not channel.logo:
            channel.logo = old_channel.logo
        for old in old_channel.streams:
            current = channel.find_stream(old.url)
            if current is not None:
                _copy_history(old, current)
                continue
            if _should_retain(old, failed_sources, cutoff):
                channel.streams.append(old)
        if channel.streams:
            merged[cid] = channel
    return merged


def _copy_history(old: Stream, new: Stream) -> None:
    for attr in ("status", "error", "error_kind", "http_status", "stream_type", "resolution",
                 "bandwidth", "segment_checked", "response_ms", "last_checked", "last_success",
                 "consecutive_failures"):
        setattr(new, attr, getattr(old, attr))
    new.first_seen = old.first_seen or new.first_seen


def _should_retain(stream: Stream, failed_sources: set[str], cutoff: datetime) -> bool:
    if stream.sources and all(src in failed_sources for src in stream.sources):
        return True
    if stream.last_success:
        try:
            return datetime.fromisoformat(stream.last_success) >= cutoff
        except ValueError:
            return False
    return False


def sort_channels(channels: Iterable[Channel]) -> list[Channel]:
    return sorted(channels, key=lambda c: strip_accents(c.name).lower())
