"""Ponto de entrada: coleta -> validação -> geração.

Uso:
    python -m src.main                 # execução completa
    python -m src.main --skip-validation
    python -m src.main --force-write   # grava mesmo sem mudanças relevantes
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from src import generator
from src.channels import Channel, build_channels, merge_with_previous
from src.collector import Collector
from src.validator import Validator

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("lista-iptv-bo")


def setup_logging(level: str, log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)
    file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        log.error("Não foi possível ler %s: %s", path, exc)
        return None


def load_previous(doc: dict | None) -> dict[str, Channel]:
    if not doc:
        return {}
    channels = {}
    for item in doc.get("channels", []):
        try:
            channel = Channel.from_dict(item)
            channels[channel.id] = channel
        except (KeyError, TypeError) as exc:
            log.warning("Entrada inválida em channels.json ignorada: %s", exc)
    return channels


def write_step_summary(stats: generator.Stats, reports: list[dict], wrote: bool) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = [
        "## Lista IPTV da Bolívia — resultado da verificação",
        "",
        f"- Canais encontrados: **{stats.channels_total}**",
        f"- Canais na lista principal: **{stats.channels_main}**",
        f"- Canais online nesta execução: **{stats.channels_online}**",
        f"- Streams online: **{stats.streams_online}/{stats.streams_total}**",
        f"- Arquivos atualizados: **{'sim' if wrote else 'não (sem mudanças relevantes)'}**",
        "",
        "| Fonte | Status | Aceitas | Rejeitadas |",
        "|---|---|---|---|",
    ]
    for r in reports:
        status = "OK" if r["ok"] else f"Falhou: {r['error']}"
        lines.append(f"| {r['name']} | {status} | {r['accepted']} | {r['rejected']} |")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


async def run(args: argparse.Namespace) -> int:
    started = time.monotonic()
    config = load_json(ROOT / "config" / "sources.json")
    if not config:
        log.error("config/sources.json ausente ou inválido")
        return 2
    rules = config.get("rules", {})
    grace_hours = float(rules.get("grace_hours", 48))
    data_path = ROOT / "data" / "channels.json"
    previous_doc = load_json(data_path)
    previous = load_previous(previous_doc)
    log.info("Estado anterior: %d canais", len(previous))

    # 1. coleta
    collection = await Collector(config, ROOT).collect()
    collected = build_channels(collection.entries)
    failed = collection.failed_sources
    if failed:
        log.warning("Fontes com falha nesta execução: %s", ", ".join(sorted(failed)))
    channels = merge_with_previous(collected, previous, failed, int(rules.get("retention_days", 7)))
    all_streams = [s for c in channels.values() for s in c.streams]
    log.info("Coleta: %d canais, %d streams únicos (%d entradas rejeitadas)",
             len(channels), len(all_streams), len(collection.rejections))

    # 2. validação
    if args.skip_validation:
        log.warning("Validação ignorada (--skip-validation)")
    else:
        log.info("Validando %d streams...", len(all_streams))
        await Validator(config.get("validator", {})).validate_all(all_streams)

    # 3. geração
    now = datetime.now(timezone.utc)
    channel_list = list(channels.values())
    stats = generator.compute_stats(channel_list, grace_hours, now)
    reports = [asdict(r) for r in collection.reports]
    log.info("Resultado: %d canais, %d na lista principal, %d online; %d/%d streams online",
             stats.channels_total, stats.channels_main, stats.channels_online,
             stats.streams_online, stats.streams_total)

    previous_online = (previous_doc or {}).get("stats", {}).get("streams_online", 0)
    if not args.skip_validation and stats.streams_online == 0 and previous_online > 0 and not args.force_write:
        log.error("Nenhum stream online (antes: %d). Provável falha de rede do executor; "
                  "arquivos preservados sem alteração.", previous_online)
        write_step_summary(stats, reports, wrote=False)
        return 1

    document = generator.build_data_document(channel_list, stats, reports, now)
    wrote = False
    if args.force_write or generator.has_material_change(previous_doc, document,
                                                         float(rules.get("heartbeat_hours", 24)), now):
        playlists = generator.build_playlists(channel_list, grace_hours, now)
        for filename, content in playlists.items():
            generator.write_text(ROOT / "playlists" / filename, content)
        generator.write_json(data_path, document)
        generator.write_json(ROOT / "data" / "report.json", {
            "generated_at": document["generated_at"],
            "duration_seconds": round(time.monotonic() - started, 1),
            "validation_skipped": bool(args.skip_validation),
            "stats": document["stats"],
            "sources": reports,
            "rejected_entries": [asdict(r) for r in collection.rejections],
            "offline_streams": [
                {"channel": c.name, "url": s.url, "error": s.error, "error_kind": s.error_kind}
                for c in generator.sort_channels(channel_list) for s in c.streams if s.status == "offline"
            ],
        })
        template_path = ROOT / "config" / "readme_template.md"
        if template_path.exists():
            readme = generator.render_readme(template_path.read_text(encoding="utf-8"), channel_list, stats,
                                             reports, config, grace_hours, now)
            generator.write_text(ROOT / "README.md", readme)
        wrote = True
        log.info("Arquivos atualizados: playlists/, data/channels.json, data/report.json, README.md")
    else:
        log.info("Sem mudanças relevantes desde a última execução; arquivos mantidos.")

    write_step_summary(stats, reports, wrote)
    log.info("Concluído em %.1fs", time.monotonic() - started)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Atualiza a lista IPTV da Bolívia")
    parser.add_argument("--skip-validation", action="store_true", help="não verifica os streams")
    parser.add_argument("--force-write", action="store_true", help="grava os arquivos mesmo sem mudanças")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args(argv)
    setup_logging(args.log_level, ROOT / "logs" / "last-run.log")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        log.warning("Interrompido pelo usuário")
        return 130


if __name__ == "__main__":
    sys.exit(main())
