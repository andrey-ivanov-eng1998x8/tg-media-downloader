import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Optional

from tg_media_downloader.metrics import DOWNLOAD_BYTES, DOWNLOAD_ERRORS, ACTIVE_WORKERS
from tg_media_downloader.queue import DownloadQueue, QueueItem

logger = logging.getLogger(__name__)


class MediaDownloader:
    def __init__(self, client, queue: DownloadQueue, dest_dir: Path, workers: int = 3, chunk_size: int = 1024 * 512):
        self.client = client
        self.queue = queue
        self.dest_dir = Path(dest_dir)
        self.num_workers = workers
        self.chunk_size = chunk_size
        self._tasks = []
        self._stop_event = asyncio.Event()

    async def start(self):
        self.dest_dir.mkdir(parents=True, exist_ok=True)
        self._stop_event.clear()
        for i in range(self.num_workers):
            t = asyncio.create_task(self._worker_loop(worker_id=i))
            self._tasks.append(t)
        logger.info("started %d downloader workers", self.num_workers)

    async def stop(self):
        self._stop_event.set()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _worker_loop(self, worker_id: int):
        while not self._stop_event.is_set():
            item = await self.queue.pop()
            if item is None:
                await asyncio.sleep(1.0)
                continue

            ACTIVE_WORKERS.inc()
            try:
                await self._process_item(item)
                await self.queue.mark_done(item.id)
            except asyncio.CancelledError:
                await self.queue.mark_retry(item.id, "worker cancelled")
                raise
            except Exception as exc:
                DOWNLOAD_ERRORS.inc()
                logger.error("worker %d failed on message %s: %s", worker_id, item.message_id, exc)
                await self.queue.mark_retry(item.id, str(exc))
            finally:
                ACTIVE_WORKERS.dec()

    async def _process_item(self, item: QueueItem):
        channel_dir = self.dest_dir / str(item.channel_id)
        channel_dir.mkdir(parents=True, exist_ok=True)

        filename = item.filename or f"media_{item.message_id}.bin"
        target_path = channel_dir / filename
        part_path = channel_dir / f"{filename}.part"

        if target_path.exists() and target_path.stat().st_size == item.expected_size:
            logger.debug("skipping existing file %s", target_path)
            return

        offset = 0
        if part_path.exists():
            offset = part_path.stat().st_size
            # If part file is somehow bigger than expected, blow it away
            if item.expected_size and offset > item.expected_size:
                part_path.unlink()
                offset = 0

        mode = "ab" if offset > 0 else "wb"
        with open(part_path, mode) as fp:
            async for chunk in self.client.stream_media(item.channel_id, item.message_id, offset=offset, chunk_size=self.chunk_size):
                if self._stop_event.is_set():
                    raise asyncio.CancelledError()
                fp.write(chunk)
                DOWNLOAD_BYTES.inc(len(chunk))

        part_path.rename(target_path)
        logger.info("downloaded %s (%d bytes)", target_path.name, target_path.stat().st_size)
