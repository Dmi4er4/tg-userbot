import logging

from telethon import TelegramClient
from telethon.tl import types

from src_py.telegram_utils.utils import get_replied_message, reply_to

logger = logging.getLogger(__name__)


async def command_id(
    client: TelegramClient,
    message: types.Message,
) -> None:
    try:
        replied = await get_replied_message(client, message)
        if replied and isinstance(replied.from_id, types.PeerUser):
            user_id = replied.from_id.user_id
            await reply_to(client, message, f"User ID: `{user_id}`")
            return

        peer = message.peer_id
        if isinstance(peer, types.PeerUser):
            await reply_to(client, message, f"User ID: `{peer.user_id}`")
        elif isinstance(peer, types.PeerChat):
            await reply_to(client, message, f"Chat ID: `{peer.chat_id}`")
        elif isinstance(peer, types.PeerChannel):
            channel_id = peer.channel_id
            await reply_to(client, message, f"Channel ID: `{channel_id}`")
    except Exception:
        logger.exception("Error handling .id")
        await reply_to(client, message, "Ошибка при получении ID.")
