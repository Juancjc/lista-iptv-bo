import asyncio

from src.channels import M3UEntry
from src.collector import Collector

CONFIG = {
    "sources": [],
    "rules": {
        "exclude_labels": ["Geo-blocked"],
        "url_block_patterns": ["token=", "dailymotion.com/video", "sec2("],
    },
}


def entry(title="Canal", url="https://x.example.com/a.m3u8", **attrs):
    return M3UEntry(title=title, url=url, attrs=attrs)


def test_reject_reasons(tmp_path):
    c = Collector(CONFIG, tmp_path)
    bo_only = {"name": "s", "require_tvg_id_suffix": ".bo"}
    groups = {"name": "s", "include_groups": ["CANALES DE BOLIVIA"]}

    assert c.reject_reason(entry(**{"tvg-id": "Unitel.bo@SantaCruz"}), bo_only) is None
    assert "não boliviano" in c.reject_reason(entry(**{"tvg-id": "ESPN.us@South"}), bo_only)
    assert "grupo" in c.reject_reason(entry(**{"group-title": "MUSICALES"}), groups)
    assert c.reject_reason(entry(**{"group-title": "CANALES DE BOLIVIA"}), groups) is None
    assert "rótulo" in c.reject_reason(entry(title="Tigo (720p) [Geo-blocked]"), {"name": "s"})
    assert "token=" in c.reject_reason(entry(url="https://x.example.com/a.php?ch=1&token=abc"), {"name": "s"})
    assert "bloqueada" in c.reject_reason(entry(url="https://www.dailymotion.com/video/x84eirw"), {"name": "s"})
    assert "inválida" in c.reject_reason(entry(url="rtmp://x.example.com/live"), {"name": "s"})
    assert "inválida" in c.reject_reason(entry(url="http://10.0.0.1/a.m3u8"), {"name": "s"})


def test_collect_local_source_and_missing_source(tmp_path):
    (tmp_path / "local.m3u").write_text(
        '#EXTM3U\n#EXTINF:-1 tvg-id="A.bo",A\nhttps://a.example.com/a.m3u8\n'
        '#EXTINF:-1 tvg-id="B.bo",B [Geo-blocked]\nhttps://b.example.com/b.m3u8\n',
        encoding="utf-8",
    )
    config = dict(CONFIG, sources=[
        {"name": "local", "path": "local.m3u"},
        {"name": "missing", "path": "nao-existe.m3u"},
        {"name": "disabled", "path": "local.m3u", "enabled": False},
    ])
    result = asyncio.run(Collector(config, tmp_path).collect())
    assert [e.url for e, _ in result.entries] == ["https://a.example.com/a.m3u8"]
    assert result.failed_sources == {"missing"}
    local = next(r for r in result.reports if r.name == "local")
    assert (local.entries, local.accepted, local.rejected) == (2, 1, 1)
    assert len(result.rejections) == 1


def test_remote_failure_falls_back_to_cache(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "remote.m3u").write_text('#EXTM3U\n#EXTINF:-1 tvg-id="A.bo",A\nhttps://a.example.com/a.m3u8\n',
                                      encoding="utf-8")
    # esquema não suportado -> falha imediata, sem acesso à rede
    config = dict(CONFIG, sources=[{"name": "remote", "url": "ftp://example.com/list.m3u"}])
    result = asyncio.run(Collector(config, tmp_path, cache_dir=cache).collect())
    report = result.reports[0]
    assert not report.ok and report.from_cache
    assert result.failed_sources == {"remote"}
    assert len(result.entries) == 1
