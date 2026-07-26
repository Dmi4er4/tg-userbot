import base64
import binascii
import io
import logging

import aiohttp
from PIL import Image
from telethon import TelegramClient
from telethon.tl import types

from src_py.telegram_utils.utils import get_replied_message, reply_to

logger = logging.getLogger(__name__)

DEFAULT_QUOTE_API_URL = "http://127.0.0.1:3000/generate"
BACKGROUND_COLOR = "#1b1429"
REQUEST_TIMEOUT_S = 30
MAX_MESSAGES = 10
STICKER_MAX_SIDE = 512

USAGE = "Использование: ответьте `.q` (или `.q <N>`) на сообщение."

_ENTITY_TYPES: dict[type, str] = {
    types.MessageEntityBold: "bold",
    types.MessageEntityItalic: "italic",
    types.MessageEntityUnderline: "underline",
    types.MessageEntityStrike: "strikethrough",
    types.MessageEntitySpoiler: "spoiler",
    types.MessageEntityCode: "code",
    types.MessageEntityPre: "pre",
    types.MessageEntityBlockquote: "blockquote",
    types.MessageEntityUrl: "url",
    types.MessageEntityTextUrl: "text_link",
    types.MessageEntityMention: "mention",
    types.MessageEntityMentionName: "text_mention",
    types.MessageEntityHashtag: "hashtag",
    types.MessageEntityCashtag: "cashtag",
    types.MessageEntityBotCommand: "bot_command",
    types.MessageEntityEmail: "email",
    types.MessageEntityPhone: "phone_number",
    types.MessageEntityCustomEmoji: "custom_emoji",
}


def _parse_count(text: str | None) -> int:
    raw = (text or "").strip()
    parts = raw.split()
    if len(parts) < 2:
        return 1
    try:
        count = int(parts[1])
    except ValueError:
        return 1
    return max(1, min(count, MAX_MESSAGES))


def _convert_entities(message: types.Message) -> list[dict]:
    result: list[dict] = []
    for ent in message.entities or []:
        kind = _ENTITY_TYPES.get(type(ent))
        if not kind:
            continue
        item: dict = {
            "type": kind,
            "offset": ent.offset,
            "length": ent.length,
        }
        if isinstance(ent, types.MessageEntityTextUrl):
            item["url"] = ent.url
        elif isinstance(ent, types.MessageEntityCustomEmoji):
            item["custom_emoji_id"] = str(ent.document_id)
        result.append(item)
    return result


async def _resolve_author(
    client: TelegramClient, message: types.Message
) -> tuple[int, str]:
    peer = message.from_id
    if peer is None and isinstance(message.peer_id, types.PeerUser):
        peer = message.peer_id

    if isinstance(peer, types.PeerChannel):
        try:
            channel = await client.get_entity(peer)
            title = getattr(channel, "title", None)
            return peer.channel_id, title or "Channel"
        except Exception:
            return peer.channel_id, "Channel"

    if not isinstance(peer, types.PeerUser):
        return 0, "Unknown"

    try:
        user = await client.get_entity(peer)
    except Exception:
        logger.exception("Failed to resolve quote author")
        return peer.user_id, f"User {peer.user_id}"

    if not isinstance(user, types.User):
        return peer.user_id, f"User {peer.user_id}"

    name = " ".join(p for p in (user.first_name, user.last_name) if p).strip()
    if not name and user.username:
        name = f"@{user.username}"
    return user.id, name or f"User {user.id}"


async def _collect_messages(
    client: TelegramClient, message: types.Message, replied: types.Message, count: int
) -> list[types.Message]:
    if count <= 1:
        return [replied]
    collected = await client.get_messages(
        message.peer_id, min_id=replied.id - 1, reverse=True, limit=count
    )
    result = [m for m in collected if isinstance(m, types.Message)]
    return result or [replied]


async def _build_payload(
    client: TelegramClient, source: list[types.Message]
) -> dict | None:
    entries: list[dict] = []
    for msg in source:
        text = (msg.message or "").strip()
        if not text:
            continue
        author_id, author_name = await _resolve_author(client, msg)
        entries.append(
            {
                "entities": _convert_entities(msg),
                "avatar": True,
                "from": {"id": author_id, "name": author_name},
                "text": msg.message,
            }
        )

    if not entries:
        return None

    return {
        "type": "quote",
        "format": "png",
        "backgroundColor": BACKGROUND_COLOR,
        "width": 512,
        "height": 768,
        "scale": 2,
        "messages": entries,
    }


async def _render_quote(payload: dict, api_url: str) -> bytes | None:
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_S)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(api_url, json=payload) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error("Quote API error %s: %s", resp.status, body)
                    return None
                data = await resp.json()
    except Exception:
        logger.exception("Quote API request failed")
        return None

    image_b64 = (data or {}).get("result", {}).get("image")
    if not image_b64:
        logger.error("Quote API returned no image: %s", data)
        return None

    try:
        return base64.b64decode(image_b64)
    except (binascii.Error, ValueError):
        logger.exception("Quote API returned malformed base64")
        return None


def _to_sticker_webp(png_bytes: bytes) -> bytes:
    image = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    longest = max(image.width, image.height)
    if longest > STICKER_MAX_SIDE:
        ratio = STICKER_MAX_SIDE / longest
        new_size = (max(1, int(image.width * ratio)), max(1, int(image.height * ratio)))
        image = image.resize(new_size, Image.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, format="WEBP", quality=90, method=6)
    return buf.getvalue()


async def command_quote(
    client: TelegramClient,
    message: types.Message,
    *,
    api_url: str = DEFAULT_QUOTE_API_URL,
) -> None:
    replied = await get_replied_message(client, message)
    if not replied:
        await reply_to(client, message, USAGE)
        return

    try:
        count = _parse_count(message.message)
        source = await _collect_messages(client, message, replied, count)
        payload = await _build_payload(client, source)
        if payload is None:
            await reply_to(client, message, "Нечего цитировать: в сообщении нет текста.")
            return

        png_bytes = await _render_quote(payload, api_url)
        if png_bytes is None:
            await reply_to(
                client, message, f"Не удалось отрендерить цитату (quote-api: {api_url})."
            )
            return

        sticker = _to_sticker_webp(png_bytes)
        file = io.BytesIO(sticker)
        file.name = "quote.webp"

        await client.send_file(
            message.peer_id,
            file,
            reply_to=replied.id,
            force_document=False,
            attributes=[types.DocumentAttributeFilename("quote.webp")],
            mime_type="image/webp",
        )

        try:
            await client.delete_messages(message.peer_id, [message.id])
        except Exception:
            logger.exception("Failed to delete .q command message")
    except Exception:
        logger.exception("Error building quote")
        await reply_to(client, message, "Ошибка при создании цитаты.")
