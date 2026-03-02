import asyncio
import difflib
import io
import logging
import time
from dataclasses import dataclass

from telethon import TelegramClient
from telethon.tl import types

from src_py.telegram_utils.media_description import format_media_message
from src_py.telegram_utils.sender_name import get_sender_display_name
from src_py.telegram_utils.utils import get_peer_label

logger = logging.getLogger(__name__)

CACHE_TTL_S = 24 * 60 * 60  # 24 hours
EVICT_INTERVAL_S = 60 * 60  # 1 hour
MIN_EDIT_CHAR_THRESHOLD = 3

MIME_TO_EXT: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "video/mp4": "mp4",
    "audio/ogg": "ogg",
    "audio/mpeg": "mp3",
    "application/pdf": "pdf",
}

MediaType = str  # "photo" | "voiceNote" | "videoNote" | "document"


@dataclass
class CachedMedia:
    data: bytes
    media_type: MediaType
    mime_type: str
    file_name: str


@dataclass
class CachedMessage:
    message_id: int
    text: str | None
    date: object
    cached_at: float
    sender_id: str | None
    sender_name: str
    peer: types.TypePeer
    chat_label: str
    media_description: str | None
    media: CachedMedia | None
    channel_id: str | None


def _count_changed_chars(old_text: str | None, new_text: str | None) -> int:
    old = old_text or ""
    new = new_text or ""
    if old == new:
        return 0
    sm = difflib.SequenceMatcher(None, old, new)
    changed = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        changed += max(i2 - i1, j2 - j1)
    return changed


def _mime_to_ext(mime: str) -> str:
    if mime in MIME_TO_EXT:
        return MIME_TO_EXT[mime]
    return mime.split("/")[-1] or "bin"


def _detect_media_type(
    message: types.Message,
) -> tuple[MediaType, str, str] | None:
    media = message.media
    if media is None:
        return None

    if isinstance(media, types.MessageMediaPhoto):
        return ("photo", "image/jpeg", "photo.jpg")

    if isinstance(media, types.MessageMediaDocument):
        doc = media.document
        if not isinstance(doc, types.Document):
            return None
        mime = doc.mime_type or "application/octet-stream"

        for attr in doc.attributes or []:
            if isinstance(attr, types.DocumentAttributeAudio) and attr.voice:
                return ("voiceNote", mime, "voice.ogg")

        for attr in doc.attributes or []:
            if isinstance(attr, types.DocumentAttributeVideo) and attr.round_message:
                return ("videoNote", mime, "video_note.mp4")

        file_name = f"file.{_mime_to_ext(mime)}"
        for attr in doc.attributes or []:
            if isinstance(attr, types.DocumentAttributeFilename):
                file_name = attr.file_name
                break

        return ("document", mime, file_name)

    return None


class DeletedMessageTracker:
    def __init__(
        self, client: TelegramClient, self_user_id: str, channel_id: int
    ) -> None:
        self._client = client
        self._self_user_id = self_user_id
        self._channel_id = channel_id
        self._cache: dict[str, CachedMessage] = {}
        self._read_up_to: dict[str, int] = {}
        self._evict_task: asyncio.Task | None = None
        self._refresh_task: asyncio.Task | None = None
        self._archived_peer_ids: set[str] = set()

    def start(self) -> None:
        self._client.add_event_handler(self._on_raw_update)
        self._evict_task = asyncio.create_task(self._evict_loop())
        self._refresh_task = asyncio.create_task(self._initial_refresh())
        logger.info("[DeletedMessageTracker] started")

    def stop(self) -> None:
        if self._evict_task:
            self._evict_task.cancel()
            self._evict_task = None
        if self._refresh_task:
            self._refresh_task.cancel()
            self._refresh_task = None

    async def _initial_refresh(self) -> None:
        try:
            await self._refresh_archived_peers()
        except Exception:
            logger.exception("[DeletedMessageTracker] initial archive refresh failed")

    async def _refresh_archived_peers(self) -> None:
        ids: set[str] = set()
        async for dialog in self._client.iter_dialogs(folder=1):
            entity = dialog.entity
            if isinstance(entity, (types.Channel, types.Chat, types.User)):
                ids.add(str(entity.id))
        self._archived_peer_ids = ids
        logger.info("[DeletedMessageTracker] refreshed archived peers: %d", len(ids))

    def _should_skip_peer(self, peer: types.TypePeer) -> bool:
        peer_id_str = self._get_raw_peer_id(peer)
        return peer_id_str is not None and peer_id_str in self._archived_peer_ids

    @staticmethod
    def _get_raw_peer_id(peer: types.TypePeer) -> str | None:
        if isinstance(peer, types.PeerUser):
            return str(peer.user_id)
        if isinstance(peer, types.PeerChat):
            return str(peer.chat_id)
        if isinstance(peer, types.PeerChannel):
            return str(peer.channel_id)
        return None

    async def cache_message(self, message: types.Message) -> None:
        if (
            isinstance(message.from_id, types.PeerUser)
            and str(message.from_id.user_id) == self._self_user_id
        ):
            return

        if self._should_skip_peer(message.peer_id):
            return

        sender_id = (
            str(message.from_id.user_id)
            if isinstance(message.from_id, types.PeerUser)
            else None
        )
        sender_name = await get_sender_display_name(self._client, message)
        media_description = format_media_message(message)
        chat_label = get_peer_label(message)

        cached_media = await self._extract_cached_media(message)

        channel_id = (
            str(message.peer_id.channel_id)
            if isinstance(message.peer_id, types.PeerChannel)
            else None
        )

        key = self._make_cache_key(message.id, channel_id)
        self._cache[key] = CachedMessage(
            message_id=message.id,
            text=message.message,
            date=message.date,
            cached_at=time.time(),
            sender_id=sender_id,
            sender_name=sender_name,
            peer=message.peer_id,
            chat_label=chat_label,
            media_description=media_description,
            media=cached_media,
            channel_id=channel_id,
        )

    async def _on_raw_update(self, update: object) -> None:
        if isinstance(update, types.UpdateReadHistoryInbox):
            self._handle_read_inbox(update)
        elif isinstance(update, types.UpdateReadChannelInbox):
            self._handle_read_channel_inbox(update)
        elif isinstance(update, types.UpdateDeleteMessages):
            await self._handle_delete_messages(update)
        elif isinstance(update, types.UpdateDeleteChannelMessages):
            await self._handle_delete_channel_messages(update)
        elif isinstance(update, types.UpdateEditMessage):
            await self._handle_edit_message(update)
        elif isinstance(update, types.UpdateEditChannelMessage):
            await self._handle_edit_channel_message(update)

    def _handle_read_inbox(self, update: types.UpdateReadHistoryInbox) -> None:
        peer_str = self._peer_to_string(update.peer)
        if peer_str:
            self._read_up_to[peer_str] = update.max_id

    def _handle_read_channel_inbox(
        self, update: types.UpdateReadChannelInbox
    ) -> None:
        self._read_up_to[f"channel:{update.channel_id}"] = update.max_id

    async def _handle_delete_messages(
        self, update: types.UpdateDeleteMessages
    ) -> None:
        for msg_id in update.messages:
            key = self._make_cache_key(msg_id, None)
            cached = self._cache.get(key)
            if not cached:
                continue
            if self._should_skip_peer(cached.peer):
                self._cache.pop(key, None)
                continue
            if self._is_unread(cached):
                try:
                    await self._send_to_saved("\U0001f5d1 Удалённое сообщение", cached)
                except Exception:
                    logger.exception("[DeletedMessageTracker] forward error")
            self._cache.pop(key, None)

    async def _handle_delete_channel_messages(
        self, update: types.UpdateDeleteChannelMessages
    ) -> None:
        channel_id = str(update.channel_id)
        if channel_id in self._archived_peer_ids:
            return
        for msg_id in update.messages:
            key = self._make_cache_key(msg_id, channel_id)
            cached = self._cache.get(key)
            if not cached:
                continue
            if self._is_unread(cached):
                try:
                    await self._send_to_saved("\U0001f5d1 Удалённое сообщение", cached)
                except Exception:
                    logger.exception("[DeletedMessageTracker] forward error")
            self._cache.pop(key, None)

    async def _handle_edit_message(
        self, update: types.UpdateEditMessage
    ) -> None:
        msg = update.message
        if not isinstance(msg, types.Message):
            return
        channel_id = (
            str(msg.peer_id.channel_id)
            if isinstance(msg.peer_id, types.PeerChannel)
            else None
        )
        key = self._make_cache_key(msg.id, channel_id)
        cached = self._cache.get(key)
        if not cached or not self._is_unread(cached):
            return

        new_text = msg.message
        new_media = await self._extract_cached_media(msg)
        media_changed = self._is_media_changed(cached.media, new_media)
        text_changed = cached.text != new_text
        if text_changed and not media_changed:
            if _count_changed_chars(cached.text, new_text) < MIN_EDIT_CHAR_THRESHOLD:
                text_changed = False
        if text_changed or media_changed:
            try:
                await self._send_edited_to_saved(cached, new_text, media_changed)
            except Exception:
                logger.exception("[DeletedMessageTracker] edit forward error")

        cached.text = new_text
        cached.media = new_media
        cached.media_description = format_media_message(msg)
        cached.cached_at = time.time()

    async def _handle_edit_channel_message(
        self, update: types.UpdateEditChannelMessage
    ) -> None:
        await self._handle_edit_message(update)

    def _is_unread(self, cached: CachedMessage) -> bool:
        if cached.channel_id:
            peer_str = f"channel:{cached.channel_id}"
        else:
            peer_str = self._peer_to_string(cached.peer)
        if not peer_str:
            return True
        max_read = self._read_up_to.get(peer_str)
        if max_read is None:
            return True
        return cached.message_id > max_read

    def _build_header(
        self, title: str, cached: CachedMessage, tag: str = "deleted"
    ) -> str:
        from datetime import datetime, timezone

        if isinstance(cached.date, datetime):
            dt = cached.date
        else:
            dt = datetime.fromtimestamp(float(cached.date), tz=timezone.utc)
        date_str = dt.strftime("%Y-%m-%d %H:%M")
        lines = [
            f"{title} #{tag}",
            f"От: {cached.sender_name}",
            f"Чат: {cached.chat_label}",
            f"Время: {date_str}",
        ]
        peer = cached.peer
        if isinstance(peer, types.PeerChannel):
            peer_id = peer.channel_id
        elif isinstance(peer, types.PeerChat):
            peer_id = peer.chat_id
        elif isinstance(peer, types.PeerUser):
            peer_id = peer.user_id
        else:
            peer_id = None
        if peer_id is not None:
            link = f"https://t.me/c/{peer_id}/{cached.message_id}"
            lines.append(f"Ссылка: {link}")
        return "\n".join(lines)

    async def _send_to_saved(
        self, title: str, cached: CachedMessage, tag: str = "deleted"
    ) -> None:
        header = self._build_header(title, cached, tag)

        if cached.media:
            caption = f"{header}\n\n{cached.text}" if cached.text else header
            await self._send_media(cached.media, caption)
        else:
            lines = [header]
            if cached.text:
                lines.extend(["", cached.text])
            if cached.media_description:
                lines.append(cached.media_description)
            if not cached.text and not cached.media_description:
                lines.append("(пустое сообщение)")
            await self._client.send_message(self._channel_id, "\n".join(lines))

        logger.info(
            "[DeletedMessageTracker] forwarded %s msg %d from %s",
            title,
            cached.message_id,
            cached.sender_name,
        )

    async def _send_edited_to_saved(
        self, cached: CachedMessage, new_text: str | None, media_changed: bool = False
    ) -> None:
        header = self._build_header("\u270f\ufe0f Изменённое сообщение", cached, "edited")
        lines = [header, ""]
        if media_changed:
            lines.append("Медиа изменено.")

        old = cached.text
        new = new_text
        if old and new:
            diff_lines = list(
                difflib.unified_diff(
                    old.splitlines(keepends=True),
                    new.splitlines(keepends=True),
                    lineterm="",
                )
            )
            # skip --- / +++ headers
            diff_body = [l for l in diff_lines if not l.startswith(("---", "+++"))]
            if diff_body:
                lines.append("\n".join(diff_body))
            else:
                lines.append("(текст не изменён)")
        elif old:
            lines.append(f"Было:\n{old}")
        elif new:
            lines.append(f"Стало:\n{new}")

        await self._client.send_message(self._channel_id, "\n".join(lines))
        logger.info(
            "[DeletedMessageTracker] forwarded edit of msg %d from %s",
            cached.message_id,
            cached.sender_name,
        )

    def _make_named_file(self, data: bytes, name: str) -> io.BytesIO:
        buf = io.BytesIO(data)
        buf.name = name
        return buf

    async def _send_media(self, media: CachedMedia, caption: str) -> None:
        dest = self._channel_id
        if media.media_type == "photo":
            f = self._make_named_file(media.data, media.file_name)
            await self._client.send_file(
                dest, f, caption=caption, force_document=False
            )
        elif media.media_type == "voiceNote":
            f = self._make_named_file(media.data, "voice.ogg")
            await self._client.send_file(
                dest, f, caption=caption, voice_note=True
            )
        elif media.media_type == "videoNote":
            await self._client.send_message(dest, caption)
            f = self._make_named_file(media.data, "video_note.mp4")
            await self._client.send_file(dest, f, video_note=True)
        else:
            f = self._make_named_file(media.data, media.file_name)
            await self._client.send_file(
                dest,
                f,
                caption=caption,
                force_document=False,
            )

    async def _extract_cached_media(self, message: types.Message) -> CachedMedia | None:
        media_info = _detect_media_type(message)
        if not media_info:
            return None

        try:
            data = await self._client.download_media(message, file=bytes)
            if not isinstance(data, bytes):
                return None
            m_type, m_mime, m_fname = media_info
            return CachedMedia(
                data=data,
                media_type=m_type,
                mime_type=m_mime,
                file_name=m_fname,
            )
        except Exception:
            logger.exception("[DeletedMessageTracker] media download error")
            return None

    @staticmethod
    def _is_media_changed(old: CachedMedia | None, new: CachedMedia | None) -> bool:
        if old is None and new is None:
            return False
        if old is None or new is None:
            return True
        return (
            old.media_type != new.media_type
            or old.mime_type != new.mime_type
            or old.file_name != new.file_name
            or old.data != new.data
        )

    def _make_cache_key(self, message_id: int, channel_id: str | None) -> str:
        if channel_id:
            return f"ch:{channel_id}:{message_id}"
        return f"msg:{message_id}"

    def _peer_to_string(self, peer: types.TypePeer) -> str | None:
        if isinstance(peer, types.PeerUser):
            return f"user:{peer.user_id}"
        if isinstance(peer, types.PeerChat):
            return f"chat:{peer.chat_id}"
        if isinstance(peer, types.PeerChannel):
            return f"channel:{peer.channel_id}"
        return None

    async def _evict_loop(self) -> None:
        while True:
            await asyncio.sleep(EVICT_INTERVAL_S)
            now = time.time()
            expired = [k for k, v in self._cache.items() if now - v.cached_at > CACHE_TTL_S]
            for k in expired:
                del self._cache[k]
            if expired:
                logger.info(
                    "[DeletedMessageTracker] evicted %d expired entries, %d remaining",
                    len(expired),
                    len(self._cache),
                )
            try:
                await self._refresh_archived_peers()
            except Exception:
                logger.exception("[DeletedMessageTracker] archive refresh failed")
