import asyncio
import logging
from typing import Optional
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, ChannelPrivateError
from telethon.tl.types import (
    MessageMediaDocument,
    MessageMediaPhoto,
    DocumentAttributeFilename,
    DocumentAttributeVideo,
    DocumentAttributeAudio,
)

from tg_media_downloader.config import Config
from tg_media_downloader.queue import QueueStorage
from tg_media_downloader.filters import should_download
from tg_media_downloader.metrics import MESSAGES_SEEN, MEDIA_ENQUEUED, FLOOD_WAIT_SECONDS

log = logging.getLogger(__name__)


def _extract_filename(media) -> Optional[str]:
    if isinstance(media, MessageMediaDocument) and media.document:
        for attr in media.document.attributes:
            if isinstance(attr, DocumentAttributeFilename):
                return attr.file_name
    return None


def _classify_media(media) -> str:
    if isinstance(media, MessageMediaPhoto):
        return "photo"
    if isinstance(media, MessageMediaDocument) and media.document:
        for attr in media.document.attributes:
            if isinstance(attr, DocumentAttributeVideo):
                return "video"
            if isinstance(attr, DocumentAttributeAudio):
                return "audio"
        return "document"
    return "unknown"


class TelegramMonitor:
    """Connects to MTProto session and watches channels for incoming media."""

    def __init__(self, config: Config, db_queue: QueueStorage):
        self.cfg = config
        self.queue = db_queue
        self.client = TelegramClient(
            config.session_name,
            config.api_id,
            config.api_hash,
        )
        self._target_entities = []

    async def start(self) -> None:
        await self.client.start(phone=self.cfg.phone if hasattr(self.cfg, "phone") else None)
        me = await self.client.get_me()
        log.info(f"logged in as @{me.username or me.id}")

        await self._resolve_channels()
        self._register_handlers()
        if self.cfg.catchup_limit > 0:
            await self.catch_up(self.cfg.catchup_limit)

    async def _resolve_channels(self) -> None:
        self._target_entities = []
        for target in self.cfg.channels:
            try:
                entity = await self.client.get_entity(target)
                self._target_entities.append(entity)
                name = getattr(entity, "title", getattr(entity, "username", str(target)))
                log.info(f"resolved channel {target} -> {name} (id: {entity.id})")
            except ChannelPrivateError:
                log.warning(f"cannot access private channel {target}")
            except Exception as e:
                log.error(f"failed to resolve {target}: {e}")

    def _register_handlers(self) -> None:
        if not self._target_entities:
            log.warning("no valid channel targets to listen on")
            return

        # FIXME: telethon drops channel cache on reconnection cycle, might need a periodic refresh
        @self.client.on(events.NewMessage(chats=self._target_entities))
        async def on_new_message(event: events.NewMessage.Event):
            msg = event.message
            chat_id = event.chat_id
            chan_title = getattr(event.chat, "title", str(chat_id))

            MESSAGES_SEEN.labels(channel=chan_title).inc()
            # print(f"DEBUG msg: {msg.id} on chat {chat_id}")

            if not msg.media:
                return

            if not should_download(msg, self.cfg):
                return

            media_type = _classify_media(msg.media)
            filename = _extract_filename(msg.media)
            file_size = getattr(msg.file, "size", 0) if msg.file else 0

            log.info(f"queuing {media_type} from {chan_title} (msg_id={msg.id})")
            self.queue.enqueue(
                channel_id=chat_id,
                channel_name=chan_title,
                message_id=msg.id,
                media_type=media_type,
                file_size=file_size,
                file_name=filename,
            )
            MEDIA_ENQUEUED.labels(channel=chan_title, media_type=media_type).inc()

    async def catch_up(self, limit: int = 50) -> None:
        log.info(f"running startup catch-up (limit={limit} msgs/channel)")
        for ent in self._target_entities:
            chan_title = getattr(ent, "title", str(ent.id))
            try:
                async for msg in self.client.iter_messages(ent, limit=limit):
                    if not msg.media:
                        continue
                    if self.queue.exists(ent.id, msg.id):
                        continue
                    if not should_download(msg, self.cfg):
                        continue

                    m_type = _classify_media(msg.media)
                    fn = _extract_filename(msg.media)
                    sz = getattr(msg.file, "size", 0) if msg.file else 0
                    self.queue.enqueue(
                        channel_id=ent.id,
                        channel_name=chan_title,
                        message_id=msg.id,
                        media_type=m_type,
                        file_size=sz,
                        file_name=fn,
                    )
                    MEDIA_ENQUEUED.labels(channel=chan_title, media_type=m_type).inc()
            except FloodWaitError as e:
                FLOOD_WAIT_SECONDS.set(e.seconds)
                log.warning(f"flood wait hit during catch-up: sleeping {e.seconds}s")
                await asyncio.sleep(e.seconds)
                FLOOD_WAIT_SECONDS.set(0)
            except Exception as e:
                log.error(f"catch-up failed on {chan_title}: {e}")

    async def run_until_disconnected(self) -> None:
        await self.client.run_until_disconnected()

    async def stop(self) -> None:
        if self.client.is_connected():
            await self.client.disconnect()
