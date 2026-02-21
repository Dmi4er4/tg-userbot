import logging
import re
from urllib.parse import quote

from telethon import TelegramClient
from telethon.tl import types

from src_py.telegram_utils.utils import get_replied_message, reply_to

logger = logging.getLogger(__name__)


def _parse_google_query(text: str | None) -> str:
    raw = (text or "").strip()
    if not raw.startswith(".g"):
        return raw
    return re.sub(r"^\.g\s*", "", raw, flags=re.IGNORECASE).strip()


def _build_google_search_url(query: str) -> str:
    return f"google.com/search?q={quote(query)}"


async def command_google(
    client: TelegramClient,
    message: types.Message,
) -> None:
    try:
        user_query = _parse_google_query(message.message)
        replied = await get_replied_message(client, message)

        search_query = user_query
        if replied and replied.message:
            replied_text = replied.message.strip()
            if user_query:
                search_query = f"{user_query} {replied_text}"
            else:
                search_query = replied_text

        if not search_query:
            await reply_to(
                client, message, "Использование: .g {текст} (можно ответом на сообщение)"
            )
            return

        url = _build_google_search_url(search_query)
        await reply_to(client, message, url)
    except Exception:
        logger.exception("Error handling .g")
        await reply_to(client, message, "Произошла ошибка при обработке запроса.")
