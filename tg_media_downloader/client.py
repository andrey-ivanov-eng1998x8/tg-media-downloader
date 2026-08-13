import logging
from typing import Optional
from telethon import TelegramClient, events
from telethon.errors import ChannelPrivateError
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
from tg_media_downloader.metrics import MESSAGES_SEEN, MEDIA_ENQUEUED

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

    async def run_until_disconnected(self) -> None:
        await self.client.run_until_disconnected()

    async def stop(self) -> None:
        if self.client.is_connected():
            await self.client.disconnect()
