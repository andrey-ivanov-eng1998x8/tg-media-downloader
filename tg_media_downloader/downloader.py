import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Optional

from tg_media_downloader.metrics import (
    DOWNLOAD_BYTES,
    DOWNLOAD_ERRORS,
    ACTIVE_WORKERS,
    FLOOD_WAIT_SECONDS,
    QUEUE_LATENCY,
)
from tg_media_downloader.queue import DownloadQueue, QueueItem

logger = logging.getLogger(__name__)


class MediaDownloader:
    """Worker pool streaming queued Telegram files to target storage directory."""

    def __init__(self,
                 client,
                 queue: DownloadQueue,
                 dest_dir: Path,
                 workers: int = 3,
                 chunk_size: int = 1024 * 512,
                 max_retries: int = 5,
                 speed_limit_kb: Optional[int] = None):
        self.client = client
        self.queue = queue
        self.dest_dir = Path(dest_dir)
        self.num_workers = workers
        self.chunk_size = chunk_size
        self.max_retries = max_retries
        self.speed_limit_bytes = (speed_limit_kb * 1024) if speed_limit_kb else None
        self._tasks = []
        self._stop_event = asyncio.Event()
        self._global_backoff_until = 0.0

    async def start(self):
        self.dest_dir.mkdir(parents=True, exist_ok=True)
        self._stop_event.clear()
        for i in range(self.num_workers):
            t = asyncio.create_task(self._worker_loop(worker_id=i), name=f"downloader-worker-{i}")
            self._tasks.append(t)
        logger.info("started %d downloader workers (chunk_size=%d KB)", self.num_workers, self.chunk_size // 1024)

    async def stop(self):
        self._stop_event.set()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("all workers stopped")

    async def _worker_loop(self, worker_id: int):
        while not self._stop_event.is_set():
            now = time.monotonic()
            if self._global_backoff_until > now:
                sleep_time = self._global_backoff_until - now
                logger.debug("worker %d waiting out flood backoff (%.1fs remaining)", worker_id, sleep_time)
                await asyncio.sleep(min(sleep_time, 2.0))
                continue

            item = await self.queue.pop()
            if item is None:
                # nothing ready, idle a bit so we don't spin sqlite
                await asyncio.sleep(0.8)
                continue

            ACTIVE_WORKERS.inc()
            if item.queued_at:
                QUEUE_LATENCY.observe(time.time() - item.queued_at)

            try:
                await self._process_item(item, worker_id)
                await self.queue.mark_done(item.id)
            except asyncio.CancelledError:
                await self.queue.mark_retry(item.id, "interrupted by shutdown")
                raise
            except Exception as exc:
                # MTProto raises FloodWaitError with value in seconds
                flood_wait = getattr(exc, "value", None) or getattr(exc, "seconds", None)
                if isinstance(flood_wait, (int, float)) and flood_wait > 0:
                    FLOOD_WAIT_SECONDS.observe(flood_wait)
                    logger.warning("flood wait hit: pausing all workers for %s seconds", flood_wait)
                    self._global_backoff_until = time.monotonic() + flood_wait + 1.0
                    await self.queue.mark_retry(item.id, f"flood wait: {flood_wait}s")
                else:
                    DOWNLOAD_ERRORS.inc()
                    logger.error("worker %d error on msg %s (ch=%s): %s", worker_id, item.message_id, item.channel_id, exc)
                    if item.retries >= self.max_retries:
                        await self.queue.mark_failed(item.id, str(exc))
                    else:
                        await self.queue.mark_retry(item.id, str(exc))
            finally:
                ACTIVE_WORKERS.dec()

    async def _process_item(self, item: QueueItem, worker_id: int):
        channel_dir = self.dest_dir / str(item.channel_id)
        channel_dir.mkdir(parents=True, exist_ok=True)

        clean_name = item.filename or f"media_{item.message_id}.bin"
        # avoid path traversal if channel metadata has crazy filenames
        clean_name = Path(clean_name).name
        target_path = channel_dir / clean_name
        part_path = channel_dir / f"{clean_name}.part"

        if target_path.exists():
            if item.expected_size and target_path.stat().st_size == item.expected_size:
                logger.debug("file %s already exists with matching size, skipping", target_path.name)
                return
            elif not item.expected_size and target_path.stat().st_size > 0:
                return

        offset = 0
        if part_path.exists():
            offset = part_path.stat().st_size
            if item.expected_size and offset > item.expected_size:
                logger.warning("orphaned part file %s is larger than expected size (%d > %d), discarding",
                               part_path.name, offset, item.expected_size)
                part_path.unlink()
                offset = 0
            elif item.expected_size and offset == item.expected_size:
                part_path.rename(target_path)
                return

        mode = "ab" if offset > 0 else "wb"
        written_in_window = 0
        window_start = time.monotonic()

        with open(part_path, mode) as fp:
            # print(f"DEBUG: worker {worker_id} chunk read starting at {offset}")
            async for chunk in self.client.stream_media(
                channel_id=item.channel_id,
                message_id=item.message_id,
                offset=offset,
                chunk_size=self.chunk_size,
            ):
                if self._stop_event.is_set():
                    raise asyncio.CancelledError()

                fp.write(chunk)
                chunk_len = len(chunk)
                DOWNLOAD_BYTES.inc(chunk_len)
                written_in_window += chunk_len

                # crude rate throttle per worker if configured
                if self.speed_limit_bytes:
                    elapsed = time.monotonic() - window_start
                    expected_time = written_in_window / (self.speed_limit_bytes / self.num_workers)
                    if expected_time > elapsed:
                        await asyncio.sleep(expected_time - elapsed)
                        window_start = time.monotonic()
                        written_in_window = 0

        # FIXME: check sha256 or tg file hash if we can get it from document object
        part_path.rename(target_path)
        logger.info("downloaded %s (%d bytes) for channel %s", target_path.name, target_path.stat().st_size, item.channel_id)
