import logging

from telethon import TelegramClient
from telethon.tl import types

logger = logging.getLogger(__name__)


async def _resolve_user_name(client: TelegramClient, peer: types.PeerUser) -> str:
    try:
        user = await client.get_entity(peer)
        if isinstance(user, types.User):
            if user.username:
                return f"@{user.username}"
            parts = [user.first_name, user.last_name]
            name = " ".join(p for p in parts if p).strip()
            if name:
                return name
            return f"User {user.id}"
    except Exception:
        logger.exception("Error getting sender display name")
    return "Unknown"


async def get_sender_display_name(
    client: TelegramClient, message: types.Message
) -> str:
    if isinstance(message.from_id, types.PeerUser):
        return await _resolve_user_name(client, message.from_id)

    if not message.from_id and isinstance(message.peer_id, types.PeerUser):
        return await _resolve_user_name(client, message.peer_id)

    return "Unknown"
