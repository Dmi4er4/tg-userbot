import logging
import re
from urllib.parse import quote

import aiohttp
from telethon import TelegramClient
from telethon.tl import types

from src_py.telegram_utils.utils import reply_to

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "tg-userbot/1.0 (https://github.com; bot)"}


def _parse_query(text: str | None) -> str:
    raw = (text or "").strip()
    return re.sub(r"^\.w\s*", "", raw, flags=re.IGNORECASE).strip()


async def _fetch_summary(
    session: aiohttp.ClientSession, lang: str, term: str
) -> dict | None:
    normalized = term.replace(" ", "_")
    encoded = quote(normalized, safe="/_")
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{encoded}"
    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with session.get(url, timeout=timeout, headers=HEADERS) as resp:
            if resp.status == 404:
                return None
            if resp.status != 200:
                logger.warning("Wikipedia %s returned %d for %r", lang, resp.status, term)
                return None
            data = await resp.json()
            if data.get("type") == "https://mediawiki.org/wiki/HyperSwitch/errors/not_found":
                return None
            return data
    except Exception:
        logger.exception("Wikipedia request failed for %s:%s", lang, term)
        return None


async def command_wiki(client: TelegramClient, message: types.Message) -> None:
    term = _parse_query(message.message)
    if not term:
        await reply_to(client, message, "Использование: .w [термин]")
        return

    try:
        async with aiohttp.ClientSession() as session:
            data = await _fetch_summary(session, "ru", term)
            lang = "ru"
            if data is None:
                data = await _fetch_summary(session, "en", term)
                lang = "en"
    except Exception:
        logger.exception("Error requesting wikipedia summary")
        await reply_to(client, message, "Ошибка при запросе к Википедии.")
        return

    if data is None:
        await reply_to(client, message, "Статья не найдена.")
        return

    title = data.get("title") or term
    extract = (data.get("extract") or "").strip()
    page_url = (
        data.get("content_urls", {})
        .get("desktop", {})
        .get("page", f"https://{lang}.wikipedia.org/wiki/{quote(term)}")
    )

    parts = [f"{title} ({lang})"]
    if extract:
        parts.extend(["", extract])
    parts.extend(["", page_url])
    await reply_to(client, message, "\n".join(parts))
