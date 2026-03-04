import logging

import aiohttp

logger = logging.getLogger(__name__)


async def send_ntfy(
    *,
    url: str,
    topic: str,
    user: str,
    password: str,
    title: str,
    message: str,
    priority: int = 4,
) -> None:
    payload = {
        "topic": topic,
        "title": title,
        "message": message,
        "priority": priority,
        "tags": ["bell"],
    }

    auth = aiohttp.BasicAuth(user, password) if user and password else None

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, auth=auth) as resp:
            if resp.status >= 400:
                body = await resp.text()
                logger.error("ntfy error %s: %s", resp.status, body)
            else:
                logger.info("ntfy notification sent: %s", title)
