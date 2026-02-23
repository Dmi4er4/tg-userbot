import logging
import re

from telethon import TelegramClient
from telethon.tl import types

from src_py.telegram_utils.sender_name import get_sender_display_name
from src_py.telegram_utils.utils import get_peer_label, get_replied_message, reply_to

logger = logging.getLogger(__name__)


def _parse_tags(text: str | None) -> list[str]:
    raw = (text or "").strip()
    first_line = raw.split("\n", 1)[0]
    after_cmd = re.sub(r"^\.save\s*", "", first_line, flags=re.IGNORECASE).strip()
    if not after_cmd:
        return ["save"]
    return after_cmd.split()


def _get_inline_text(text: str | None) -> str | None:
    raw = (text or "").strip()
    parts = raw.split("\n", 1)
    if len(parts) < 2:
        return None
    body = parts[1].strip()
    return body or None


def _format_tags_header(tags: list[str]) -> str:
    return " ".join(f"#{t}" for t in tags)


async def command_save(
    client: TelegramClient,
    message: types.Message,
    *,
    channel_id: object,
) -> None:
    tags = _parse_tags(message.message)
    inline_text = _get_inline_text(message.message)
    replied = await get_replied_message(client, message)

    if not replied and not inline_text:
        await reply_to(
            client, message, "Ответьте на сообщение или напишите текст после .save"
        )
        return

    try:
        if replied:
            await _forward_message(client, replied, channel_id, tags)
        if inline_text:
            await _send_inline_text(client, message, channel_id, tags, inline_text)
        await client.delete_messages(message.peer_id, [message.id], revoke=True)
    except Exception:
        logger.exception("Error handling .save")
        await reply_to(client, message, "Ошибка при сохранении сообщения.")


async def _forward_message(
    client: TelegramClient,
    message: types.Message,
    channel_id: object,
    tags: list[str],
) -> None:
    sender_name = await get_sender_display_name(client, message)
    chat_label = get_peer_label(message)
    header = f"{_format_tags_header(tags)}\nОт: {sender_name}\nЧат: {chat_label}"

    if message.media:
        await client.send_message(channel_id, header)
        await client.forward_messages(channel_id, message)
    else:
        lines = [header]
        if message.message:
            lines.extend(["", message.message])
        await client.send_message(channel_id, "\n".join(lines))


async def _send_inline_text(
    client: TelegramClient,
    message: types.Message,
    channel_id: object,
    tags: list[str],
    text: str,
) -> None:
    chat_label = get_peer_label(message)
    header = f"{_format_tags_header(tags)}\nЧат: {chat_label}"
    await client.send_message(channel_id, f"{header}\n\n{text}")
