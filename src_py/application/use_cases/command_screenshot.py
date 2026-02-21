import io
import logging
import re
from urllib.parse import quote, urlparse

import aiohttp
from telethon import TelegramClient
from telethon.tl import types

from src_py.telegram_utils.utils import reply_to

logger = logging.getLogger(__name__)


def _parse_url(text: str | None) -> str:
    raw = (text or "").strip()
    raw = re.sub(r"^\.ss\s*", "", raw, flags=re.IGNORECASE).strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme:
        return raw
    return f"https://{raw}"


async def command_screenshot(client: TelegramClient, message: types.Message) -> None:
    url = _parse_url(message.message)
    if not url:
        await reply_to(client, message, "Использование: .ss [url]")
        return

    encoded_url = quote(url, safe=":/%&=")
    api_url = f"https://image.thum.io/get/{encoded_url}"

    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=timeout) as resp:
                if resp.status != 200:
                    await reply_to(client, message, "Не удалось сделать скриншот сайта.")
                    return
                data = await resp.read()
    except Exception:
        logger.exception("Error loading screenshot from thum.io")
        await reply_to(client, message, "Ошибка при получении скриншота.")
        return

    image = io.BytesIO(data)
    image.name = "screenshot.png"
    await client.send_file(
        message.peer_id, image, reply_to=message.id, force_document=False
    )
