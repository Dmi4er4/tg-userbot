import io
import logging

from PIL import Image
from telethon import TelegramClient
from telethon.tl import types

from src_py.telegram_utils.utils import get_replied_message, reply_to

logger = logging.getLogger(__name__)


def _is_static_sticker(message: types.Message) -> bool:
    media = message.media
    if not isinstance(media, types.MessageMediaDocument):
        return False
    doc = media.document
    if not isinstance(doc, types.Document):
        return False
    is_sticker = any(
        isinstance(a, types.DocumentAttributeSticker) for a in (doc.attributes or [])
    )
    if not is_sticker:
        return False
    mime = (doc.mime_type or "").lower()
    return mime == "image/webp"


def _convert_webp_to_png(data: bytes) -> io.BytesIO:
    img = Image.open(io.BytesIO(data))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    buf.name = "sticker.png"
    return buf


async def command_sticker_to_photo(
    client: TelegramClient,
    message: types.Message,
) -> None:
    replied = await get_replied_message(client, message)
    if not replied or not _is_static_sticker(replied):
        await reply_to(
            client, message, "Ответьте командой .sticker на статичный стикер."
        )
        return

    try:
        data = await client.download_media(replied, file=bytes)
        if not isinstance(data, bytes):
            await reply_to(client, message, "Не удалось скачать стикер.")
            return

        png = _convert_webp_to_png(data)
        await client.send_file(
            message.peer_id, png, reply_to=message.id, force_document=False
        )
    except Exception:
        logger.exception("Error converting sticker")
        await reply_to(client, message, "Ошибка при конвертации стикера.")
