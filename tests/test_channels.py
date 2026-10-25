from datetime import datetime, timedelta, timezone

import pytest

from src.channels import (
    STATUS_ONLINE,
    Channel,
    Stream,
    UnsafeURLError,
    build_channels,
    check_url,
    extract_labels,
    map_category,
    merge_with_previous,
    name_key,
    normalize_tvg_id,
    parse_m3u,
    pretty_name,
    slug_id,
)

SAMPLE = """﻿#EXTM3U
#EXTINF:-1 tvg-id="BoliviaTV.bo@SD" tvg-logo="https://x/logo.png" group-title="General",Bolivia TV (1080p)
http://203.0.113.1:8000/play/a001/index.m3u8

#EXTINF:-1 tvg-id="UPEATV.bo@SD" http-referrer="https://tv.upea.bo/live" group-title="Undefined",UPEA, TV (720p)
#EXTVLCOPT:http-user-agent=TestAgent/1.0
https://tvstream.upea.bo/hls/x.m3u8
#EXTINF:-1 tvg-id="Comma.bo" tvg-name="A, B" group-title="News",Nome, com vírgula [Not 24/7]
https://example.com/a.m3u8
#EXTINF:-1,Sem URL
"""


def test_parse_m3u_attributes_options_and_titles():
    entries = parse_m3u(SAMPLE, source="t")
    assert len(entries) == 3
    first, second, third = entries
    assert first.tvg_id == "BoliviaTV.bo@SD"
    assert first.logo == "https://x/logo.png"
    assert first.group == "General"
    assert first.title == "Bolivia TV (1080p)"
    assert second.referrer == "https://tv.upea.bo/live"
    assert second.user_agent == "TestAgent/1.0"
    assert second.title == "UPEA, TV (720p)"
    assert third.attrs["tvg-name"] == "A, B"
    assert third.title == "Nome, com vírgula [Not 24/7]"
    assert all(e.source == "t" for e in entries)


def test_parse_m3u_tolerates_garbage():
    assert parse_m3u("") == []
    assert parse_m3u("not a playlist\nhttp://x") == []


@pytest.mark.parametrize("url", [
    "ftp://example.com/x.m3u8",
    "javascript:alert(1)",
    "https://",
    "https://user:pass@example.com/x.m3u8",
    "https://exa mple.com/x.m3u8",
    "http://127.0.0.1/x.m3u8",
    "http://192.168.0.10/x.m3u8",
    "http://localhost:8080/x.m3u8",
    "http://example.com:99999/x.m3u8",
    "https://example.com/" + "a" * 3000,
])
def test_check_url_rejects_bad_urls(url):
    with pytest.raises(UnsafeURLError):
        check_url(url)


def test_check_url_accepts_public_and_normalizes():
    assert check_url("HTTPS://Example.COM/Live/Index.m3u8") == "https://example.com/Live/Index.m3u8"
    assert check_url("http://190.181.61.93:8000/play/a/index.m3u8")
    assert check_url("http://127.0.0.1/x", allow_private=True)


def test_labels_and_name_keys():
    assert extract_labels("CEACOM TV (1080p) [Not 24/7]") == ("CEACOM TV", ["Not 24/7"])
    assert name_key("RED UNO LPZ HD") == "red uno lpz"
    assert name_key("PACEÑISIMA TV HD") == "pacenisima tv"
    assert name_key("BTV 7.2 HD") == "btv 7.2"
    assert name_key("CTV (Bolivia) (1080p)") == "ctv"
    assert slug_id("Zoy TV HD") == "ZoyTV.bo"
    assert slug_id("RED SIGLO XXI HD") == "RedSigloXXI.bo"
    assert pretty_name("RED SIGLO XXI HD") == "Red Siglo XXI"
    assert pretty_name("Univalle Televisión (1080p)") == "Univalle Televisión"
    assert pretty_name("F10 HD") == "F10"
    assert pretty_name("Sol TV (Bolivia) (720p)") == "Sol TV"


def test_regional_channels_share_logo():
    text = """#EXTM3U
#EXTINF:-1 tvg-id="UnitelLaPaz.bo@SD",Unitel La Paz
https://u.example.com/lp.m3u8
#EXTINF:-1 tvg-id="Unitel.bo@SantaCruz" tvg-logo="https://l/unitel.png",Unitel
https://u.example.com/scz.m3u8
#EXTINF:-1 tvg-id="Other.bo",Other
https://o.example.com/x.m3u8
"""
    channels = build_channels(_entries(text, "a"))
    assert channels["UnitelLaPaz.bo"].logo == "https://l/unitel.png"
    assert channels["Other.bo"].logo == ""


def test_normalize_tvg_id_keeps_regional_feeds():
    assert normalize_tvg_id("Bolivision.bo@SD") == "Bolivision.bo"
    assert normalize_tvg_id("Unifranz.bo@HD") == "Unifranz.bo"
    assert normalize_tvg_id("RedUno.bo@LaPaz") == "RedUno.bo@LaPaz"
    assert normalize_tvg_id("RedUnoSantaCruz.bo@SD") == "RedUno.bo@SantaCruz"


def test_map_category():
    assert map_category("Culture;Education;News") == "Cultural"
    assert map_category("Undefined") == "Geral"
    assert map_category("") == "Geral"


def _entries(text, source, use_tvg_id=True):
    return [(e, use_tvg_id) for e in parse_m3u(text, source)]


def test_build_channels_deduplicates_and_keeps_alternatives():
    a = """#EXTM3U
#EXTINF:-1 tvg-id="CoralTV.bo@SD" tvg-logo="https://l/coral.png" group-title="General",Coral TV (720p)
https://tv.example.com/coraltv/index.m3u8
#EXTINF:-1 tvg-id="RTP.bo@SD" group-title="General",RTP (576p)
https://rtp.example.com/hls720/stream3.m3u8
"""
    b = """#EXTM3U
#EXTINF:-1 tvg-id="CoralTV.bo@SD",Coral TV
HTTPS://TV.EXAMPLE.COM/coraltv/index.m3u8
#EXTINF:-1 tvg-id="RTP.bo@SD",RTP (480p)
https://rtp.example.com/hls480/stream2.m3u8
"""
    c = """#EXTM3U
#EXTINF:-1 tvg-id="CORAL TV" group-title="CANALES DE BOLIVIA",CORAL TV
https://tv.example.com/coraltv/tracks-v1a1/mono.ts.m3u8
#EXTINF:-1 tvg-id="X" group-title="CANALES DE BOLIVIA",RTP LA PAZ HD
https://rtp.example.com/hls720/stream3.m3u8
#EXTINF:-1 group-title="CANALES DE BOLIVIA",ZOY TV HD
https://zoy.example.com/live.m3u8
"""
    entries = _entries(a, "a") + _entries(b, "b") + _entries(c, "c", use_tvg_id=False)
    channels = build_channels(entries)

    coral = channels["CoralTV.bo"]
    assert coral.logo == "https://l/coral.png"
    assert [s.url for s in coral.streams] == [
        "https://tv.example.com/coraltv/index.m3u8",
        "https://tv.example.com/coraltv/tracks-v1a1/mono.ts.m3u8",
    ]
    assert coral.streams[0].sources == ["a", "b"]

    rtp = channels["RTP.bo"]
    assert len(rtp.streams) == 2
    assert rtp.streams[0].sources == ["a", "c"]  # mesma URL vinda de outra fonte não duplica

    assert channels["ZoyTV.bo"].name == "Zoy TV"


def test_build_channels_uses_catalog_metadata():
    text = '#EXTM3U\n#EXTINF:-1 tvg-id="UMSATVULP.bo@SD" group-title="Culture;Education",UMSA TVU LP (720p)\nhttps://e.example.com/8190/index.m3u8\n'
    ch = build_channels(_entries(text, "a"))["UMSATVULP.bo"]
    assert ch.name == "UMSA TVU La Paz"
    assert ch.category == "Universitário"
    assert ch.group_title == "Bolívia | Universitário"


def test_merge_preserves_history_and_failed_sources():
    now = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
    old_ok = Stream(url="https://a.example.com/1.m3u8", sources=["src1"], status=STATUS_ONLINE,
                    last_success=(now - timedelta(hours=6)).isoformat(), last_checked="x")
    from_failed_source = Stream(url="https://b.example.com/2.m3u8", sources=["down"], status=STATUS_ONLINE)
    removed_recent = Stream(url="https://c.example.com/3.m3u8", sources=["src1"],
                            last_success=(now - timedelta(days=2)).isoformat())
    removed_old = Stream(url="https://d.example.com/4.m3u8", sources=["src1"],
                         last_success=(now - timedelta(days=30)).isoformat())
    never_ok = Stream(url="https://e.example.com/5.m3u8", sources=["src1"])
    previous = {
        "X.bo": Channel(id="X.bo", name="X", logo="https://l/x.png",
                        streams=[old_ok, from_failed_source, removed_recent, removed_old, never_ok]),
        "Gone.bo": Channel(id="Gone.bo", name="Gone", streams=[Stream(url="https://g.example.com/x", sources=["src1"])]),
    }
    collected = {"X.bo": Channel(id="X.bo", name="X", streams=[Stream(url="https://a.example.com/1.m3u8",
                                                                      sources=["src1"])])}
    merged = merge_with_previous(collected, previous, failed_sources={"down"}, retention_days=7, now=now)

    urls = [s.url for s in merged["X.bo"].streams]
    assert urls == ["https://a.example.com/1.m3u8", "https://b.example.com/2.m3u8", "https://c.example.com/3.m3u8"]
    assert merged["X.bo"].streams[0].status == STATUS_ONLINE
    assert merged["X.bo"].streams[0].last_checked == "x"
    assert merged["X.bo"].logo == "https://l/x.png"
    assert "Gone.bo" not in merged


def test_channel_roundtrip_dict():
    ch = Channel(id="A.bo", name="A", streams=[Stream(url="https://a.example.com/x.m3u8", sources=["s"])])
    data = ch.to_dict()
    data["streams"][0]["unknown_future_field"] = 1
    again = Channel.from_dict(data)
    assert again.streams[0].url == "https://a.example.com/x.m3u8"
