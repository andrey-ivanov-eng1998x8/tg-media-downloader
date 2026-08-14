import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from tg_media_downloader.config import Config, load_config
from tg_media_downloader.client import TelegramScraper
from tg_media_downloader.downloader import MediaDownloader
from tg_media_downloader.queue import DownloadQueue
from tg_media_downloader.metrics import start_metrics_server


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tg-media-downloader", description="Tails Telegram channels and downloads media")
    p.add_argument("-c", "--config", type=Path, default=Path("config.toml"), help="Path to config.toml")
    p.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    p.add_argument("--dry-run", action="store_true", help="Queue incoming media but do not start download workers")
    return p


async def run_daemon(cfg: Config, dry_run: bool = False):
    queue = DownloadQueue(cfg.database_path)
    await queue.init_db()

    if cfg.metrics_port:
        start_metrics_server(cfg.metrics_host, cfg.metrics_port)

    client = TelegramScraper(cfg)
    downloader = None if dry_run else MediaDownloader(client, queue, cfg.storage_path, workers=cfg.workers)

    await client.connect()
    if downloader:
        await downloader.start()

    try:
        await client.run_listener(queue)
    finally:
        if downloader:
            await downloader.stop()
        await client.disconnect()


def main():
    parser = build_parser()
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    if not args.config.exists():
        sys.exit(f"Config file not found: {args.config}")

    cfg = load_config(args.config)
    asyncio.run(run_daemon(cfg, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
