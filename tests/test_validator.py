import asyncio

import pytest
from aiohttp import web

from src.channels import ERROR_PERMANENT, ERROR_TRANSIENT, STATUS_OFFLINE, STATUS_ONLINE, Stream
from src.validator import CheckFailed, Validator, analyze_playlist, check_dash, sniff_media

TS = bytes([0x47] + [0] * 187) * 4
FMP4 = b"\x00\x00\x00\x18ftypiso6" + b"\x00" * 64

MASTER = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1280x720
hi/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360
lo/index.m3u8
"""

MEDIA = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:6
#EXT-X-MEDIA-SEQUENCE:10
#EXTINF:6.0,
seg10.ts
#EXTINF:6.0,
seg11.ts
"""


# ---------------------------------------------------------------------------
# funções puras
# ---------------------------------------------------------------------------


def test_analyze_master_playlist_resolves_relative_urls():
    info = analyze_playlist(MASTER, "https://cdn.example.com/live/master.m3u8")
    assert info.kind == "master"
    assert [v.url for v in info.variants] == [
        "https://cdn.example.com/live/hi/index.m3u8",
        "https://cdn.example.com/live/lo/index.m3u8",
    ]
    assert info.variants[0].resolution == "1280x720"
    assert info.variants[1].bandwidth == 800000


def test_analyze_media_playlist():
    info = analyze_playlist(MEDIA, "https://cdn.example.com/live/lo/index.m3u8")
    assert info.kind == "media"
    assert info.target_duration == 6
    assert info.segments[-1] == "https://cdn.example.com/live/lo/seg11.ts"


@pytest.mark.parametrize("text,msg", [
    ("<html>oops</html>", "#EXTM3U"),
    ("#EXTM3U\n#EXT-X-VERSION:3\n", "sem segmentos"),
    ("#EXTM3U\n#EXTINF:6,\nseg.ts\n", "TARGETDURATION"),
    ("#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI=\"skd://x\"\n#EXTINF:6,\na.ts\n", "DRM"),
    ('#EXTM3U\n#EXT-X-SESSION-KEY:METHOD=AES-128,KEYFORMAT="com.widevine",URI="x"\n'
     '#EXT-X-STREAM-INF:BANDWIDTH=1\na.m3u8\n', "DRM"),
])
def test_analyze_invalid_playlists(text, msg):
    with pytest.raises(CheckFailed, match=msg):
        analyze_playlist(text, "https://x.example.com/a.m3u8")


def test_aes128_is_not_drm():
    text = '#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXT-X-KEY:METHOD=AES-128,URI="k.key"\n#EXTINF:6,\na.ts\n'
    info = analyze_playlist(text, "https://x.example.com/a.m3u8")
    assert info.encrypted and not info.drm


def test_sniff_media():
    assert sniff_media(TS) == "ts"
    assert sniff_media(FMP4) == "fmp4"
    assert sniff_media(b"ID3\x04\x00") == "id3"
    assert sniff_media(b"\xff\xf1\x50\x80") == "aac"
    assert sniff_media(b"<html>") is None


def test_check_dash():
    ok = '<?xml version="1.0"?><MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><Period><AdaptationSet/></Period></MPD>'
    check_dash(ok)
    with pytest.raises(CheckFailed, match="DRM"):
        check_dash('<MPD><Period><AdaptationSet><ContentProtection/></AdaptationSet></Period></MPD>')
    with pytest.raises(CheckFailed):
        check_dash("<MPD><broken")


# ---------------------------------------------------------------------------
# validação com servidor HTTP local
# ---------------------------------------------------------------------------


def make_app(state):
    async def master(_):
        return web.Response(text=MASTER, content_type="application/vnd.apple.mpegurl")

    async def media(_):
        return web.Response(text=MEDIA, content_type="application/vnd.apple.mpegurl")

    async def segment(_):
        return web.Response(body=TS, content_type="video/mp2t")

    async def html_segment(_):
        return web.Response(text="<!DOCTYPE html><html></html>", content_type="text/html")

    async def html(_):
        return web.Response(text="<!DOCTYPE html><html><body>player</body></html>", content_type="text/html")

    async def not_found(_):
        return web.Response(status=404)

    async def flaky(_):
        state["flaky"] += 1
        if state["flaky"] == 1:
            return web.Response(status=503)
        return web.Response(text=MEDIA, content_type="application/vnd.apple.mpegurl")

    async def needs_referrer(request):
        if request.headers.get("Referer") != "https://site.example/":
            return web.Response(status=403)
        return web.Response(text=MEDIA, content_type="application/vnd.apple.mpegurl")

    async def raw_ts(request):
        resp = web.StreamResponse(headers={"Content-Type": "video/mp2t"})
        await resp.prepare(request)
        for _ in range(5):  # simula transmissão contínua
            await resp.write(TS * 10)
        return resp

    async def slow(_):
        await asyncio.sleep(5)
        return web.Response(text=MEDIA)

    async def bad_segment_playlist(_):
        return web.Response(text=MEDIA.replace("seg11.ts", "/htmlseg"), content_type="application/vnd.apple.mpegurl")

    app = web.Application()
    app.router.add_get("/master.m3u8", master)
    app.router.add_get("/hi/index.m3u8", media)
    app.router.add_get("/lo/index.m3u8", media)
    app.router.add_get("/media.m3u8", media)
    app.router.add_get("/{seg:(hi/|lo/)?seg1[01].ts}", segment)
    app.router.add_get("/htmlseg", html_segment)
    app.router.add_get("/page.m3u8", html)
    app.router.add_get("/missing.m3u8", not_found)
    app.router.add_get("/flaky.m3u8", flaky)
    app.router.add_get("/ref.m3u8", needs_referrer)
    app.router.add_get("/live.ts", raw_ts)
    app.router.add_get("/slow.m3u8", slow)
    app.router.add_get("/badseg.m3u8", bad_segment_playlist)
    return app


async def _validate(paths, referrers=None):
    state = {"flaky": 0}
    runner = web.AppRunner(make_app(state))
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        streams = []
        for path in paths:
            s = Stream(url=f"http://127.0.0.1:{port}{path}")
            s.referrer = (referrers or {}).get(path)
            streams.append(s)
        validator = Validator({"timeout_seconds": 1, "retries": 1, "concurrency": 4}, allow_private=True)
        await validator.validate_all(streams)
        return {p: s for p, s in zip(paths, streams)}
    finally:
        await runner.cleanup()


def run_validation(paths, referrers=None):
    return asyncio.run(_validate(paths, referrers))


def test_validator_end_to_end():
    results = run_validation(
        ["/master.m3u8", "/media.m3u8", "/page.m3u8", "/missing.m3u8", "/flaky.m3u8", "/ref.m3u8",
         "/live.ts", "/badseg.m3u8"],
        referrers={"/ref.m3u8": "https://site.example/"},
    )
    master = results["/master.m3u8"]
    assert master.status == STATUS_ONLINE
    assert master.stream_type == "hls"
    assert master.resolution == "1280x720"
    assert master.segment_checked
    assert master.last_success and master.consecutive_failures == 0

    assert results["/media.m3u8"].status == STATUS_ONLINE

    page = results["/page.m3u8"]
    assert page.status == STATUS_OFFLINE
    assert "HTML" in page.error and page.error_kind == ERROR_PERMANENT

    missing = results["/missing.m3u8"]
    assert missing.status == STATUS_OFFLINE and missing.http_status == 404
    assert missing.consecutive_failures == 1

    assert results["/flaky.m3u8"].status == STATUS_ONLINE  # 503 seguido de sucesso na nova tentativa
    assert results["/ref.m3u8"].status == STATUS_ONLINE
    assert results["/live.ts"].stream_type == "ts" and results["/live.ts"].status == STATUS_ONLINE

    badseg = results["/badseg.m3u8"]
    assert badseg.status == STATUS_OFFLINE and "segmento" in badseg.error


def test_validator_timeout_is_transient():
    results = run_validation(["/slow.m3u8"])
    slow = results["/slow.m3u8"]
    assert slow.status == STATUS_OFFLINE
    assert slow.error_kind == ERROR_TRANSIENT


def test_validator_rejects_private_hosts_by_default():
    stream = Stream(url="http://127.0.0.1:9/x.m3u8")
    asyncio.run(Validator({"timeout_seconds": 1}).validate_all([stream]))
    assert stream.status == STATUS_OFFLINE
    assert "URL rejeitada" in stream.error
