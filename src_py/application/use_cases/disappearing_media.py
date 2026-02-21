import io
import logging

from telethon import TelegramClient
from telethon.tl import types

from src_py.telegram_utils.sender_name import get_sender_display_name
from src_py.telegram_utils.utils import get_peer_label

logger = logging.getLogger(__name__)


def is_disappearing_media(message: types.Message) -> bool:
    if not message.media:
        return False
    ttl = getattr(message.media, "ttl_seconds", None)
    return ttl is not None and ttl > 0


async def forward_disappearing_media(
    client: TelegramClient,
    message: types.Message,
    *,
    channel_id: object,
) -> None:
    try:
        data = await client.download_media(message, file=bytes)
        if not isinstance(data, bytes):
            return

        sender_name = await get_sender_display_name(client, message)
        chat_label = get_peer_label(message)
        header = f"#disappearing\nОт: {sender_name}\nЧат: {chat_label}"

        f = io.BytesIO(data)
        f.name = "disappearing.jpg"
        await client.send_file(channel_id, f, caption=header, force_document=False)
        logger.info("Forwarded disappearing media from %s", sender_name)
    except Exception:
        logger.exception("Error forwarding disappearing media")
