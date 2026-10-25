from datetime import datetime, timedelta, timezone

from src.channels import ERROR_PERMANENT, ERROR_TRANSIENT, STATUS_OFFLINE, STATUS_ONLINE, Channel, Stream, parse_m3u
from src.generator import (
    PLAYLIST_ALL,
    PLAYLIST_MAIN,
    PLAYLIST_ONLINE,
    build_data_document,
    build_playlists,
    compute_stats,
    has_material_change,
    is_usable,
    render_readme,
)

NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)


def iso(hours_ago):
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def sample_channels():
    a = Channel(id="BoliviaTV.bo", name="Bolivia TV", logo="https://l/btv.png", category="TV Pública", streams=[
        Stream(url="https://a.example.com/slow.m3u8", status=STATUS_ONLINE, stream_type="hls",
               segment_checked=True, resolution="1280x720", response_ms=900, last_success=iso(0)),
        Stream(url="https://a.example.com/fast.m3u8", status=STATUS_ONLINE, stream_type="hls",
               segment_checked=True, resolution="1920x1080", response_ms=100, last_success=iso(0),
               referrer="https://site.example/", user_agent="UA/1"),
        Stream(url="https://a.example.com/dead.m3u8", status=STATUS_OFFLINE, error="HTTP 404",
               error_kind=ERROR_PERMANENT),
    ])
    b = Channel(id="Flaky.bo", name="Canal \"Instável\"", category="Geral", streams=[
        Stream(url="https://b.example.com/x.m3u8", status=STATUS_OFFLINE, error_kind=ERROR_TRANSIENT,
               last_success=iso(10)),
    ])
    c = Channel(id="Dead.bo", name="Ántigo", category="Geral", streams=[
        Stream(url="https://c.example.com/x.m3u8", status=STATUS_OFFLINE, error_kind=ERROR_TRANSIENT,
               last_success=iso(100)),
    ])
    return [a, b, c]


def test_is_usable_grace_period():
    ok, flaky, dead = (ch.streams[0] for ch in sample_channels())
    assert is_usable(ok, 48, NOW)
    assert is_usable(flaky, 48, NOW)
    assert not is_usable(dead, 48, NOW)
    assert not is_usable(Stream(url="x", status=STATUS_OFFLINE, error_kind=ERROR_PERMANENT,
                                last_success=iso(1)), 48, NOW)


def test_build_playlists_contents():
    playlists = build_playlists(sample_channels(), 48, NOW)
    for text in playlists.values():
        assert text.startswith("#EXTM3U\n")
        assert text.endswith("\n")

    main = parse_m3u(playlists[PLAYLIST_MAIN])
    assert [e.title for e in main] == ["Bolivia TV", 'Canal "Instável"']
    assert main[0].url == "https://a.example.com/fast.m3u8"  # melhor resolução / mais rápido
    assert main[0].referrer == "https://site.example/" and main[0].user_agent == "UA/1"
    assert main[0].attrs["group-title"] == "Bolívia | TV Pública"
    assert main[0].attrs["tvg-id"] == "BoliviaTV.bo"
    assert main[0].logo == "https://l/btv.png"
    assert '#EXTVLCOPT:http-referrer=https://site.example/' in playlists[PLAYLIST_MAIN]

    online = parse_m3u(playlists[PLAYLIST_ONLINE])
    assert [e.title for e in online] == ["Bolivia TV", "Bolivia TV (Alt. 2)"]

    every = parse_m3u(playlists[PLAYLIST_ALL])
    assert len(every) == 5
    assert "Bolivia TV (Alt. 3) [Offline]" in [e.title for e in every]
    assert every[-1].title == 'Canal "Instável" [Offline]'


def test_stats_and_material_change():
    channels = sample_channels()
    stats = compute_stats(channels, 48, NOW)
    assert (stats.channels_total, stats.channels_main, stats.channels_online) == (3, 2, 1)
    assert (stats.streams_total, stats.streams_online) == (5, 2)

    doc = build_data_document(channels, stats, [], NOW)
    later = NOW + timedelta(hours=6)
    channels[0].streams[0].last_checked = later.isoformat()
    channels[0].streams[0].response_ms = 123
    doc2 = build_data_document(channels, stats, [], later)
    assert not has_material_change(doc, doc2, 24, later)  # só campos voláteis mudaram
    assert has_material_change(doc, doc2, 24, NOW + timedelta(hours=25))  # heartbeat diário

    channels[1].streams[0].status = STATUS_ONLINE
    doc3 = build_data_document(channels, stats, [], later)
    assert has_material_change(doc, doc3, 24, later)
    assert has_material_change(None, doc3, 24, later)


def test_render_readme(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "fulano/lista-iptv-bo")
    monkeypatch.delenv("GITHUB_REF_TYPE", raising=False)
    channels = sample_channels()
    stats = compute_stats(channels, 48, NOW)
    sources = [{"name": "s1", "ok": True, "accepted": 3, "rejected": 1},
               {"name": "s2", "ok": False, "from_cache": False, "accepted": 0, "rejected": 0}]
    tpl = "$repo|$raw_main|$channels_total|$channels_online|$updated_at\n$channel_table\n$source_table"
    out = render_readme(tpl, channels, stats, sources, {"branch": "main"}, 48, NOW)
    assert out.startswith("fulano/lista-iptv-bo|https://raw.githubusercontent.com/fulano/lista-iptv-bo/main/"
                          "playlists/bolivia.m3u|3|1|25/10/2026 08:00")
    assert "| Bolivia TV | TV Pública | — | 🟢 Online | 2/3 |" in out
    assert "🟡 Instável" in out and "🔴 Offline" in out
    assert "| `s2` | ❌ Falhou | 0 | 0 |" in out
