import logging
import re

from telethon import TelegramClient
from telethon.tl import types

from src_py.telegram_utils.sender_name import get_sender_display_name
from src_py.telegram_utils.utils import get_peer_label, get_replied_message, reply_to

logger = logging.getLogger(__name__)


def _parse_tag(text: str | None) -> str:
    raw = (text or "").strip()
    tag = re.sub(r"^\.save\s*", "", raw, flags=re.IGNORECASE).strip()
    return tag or "save"


async def command_save(
    client: TelegramClient,
    message: types.Message,
    *,
    channel_id: object,
) -> None:
    replied = await get_replied_message(client, message)
    if not replied:
        await reply_to(client, message, "Ответьте командой .save на сообщение.")
        return

    tag = _parse_tag(message.message)

    try:
        await _forward_message(client, replied, channel_id, tag)
        await client.delete_messages(message.peer_id, [message.id], revoke=True)
    except Exception:
        logger.exception("Error handling .save")
        await reply_to(client, message, "Ошибка при сохранении сообщения.")


async def _forward_message(
    client: TelegramClient,
    message: types.Message,
    channel_id: object,
    tag: str,
) -> None:
    sender_name = await get_sender_display_name(client, message)
    chat_label = get_peer_label(message)
    header = f"#{tag}\nОт: {sender_name}\nЧат: {chat_label}"

    if message.media:
        await client.send_message(channel_id, header)
        await client.forward_messages(channel_id, message)
    else:
        lines = [header]
        if message.message:
            lines.extend(["", message.message])
        await client.send_message(channel_id, "\n".join(lines))
