import logging
import re

from telethon import TelegramClient
from telethon.tl import types

from src_py import messages
from src_py.telegram_utils.utils import get_replied_message

logger = logging.getLogger(__name__)

DISCLAIMER_TEXT = (
    "Не является финансовым, инвестиционным или юридическим советом.\n"
    "Вся информация приведена исключительно в образовательных и исследовательских целях.\n"
    "Любые совпадения с реальными действиями и событиями случайны.\n"
    "Все описанное рассматривается только в теоретическом ключе.\n"
    "Происходит в вымышленном контексте (в GTA 5 RP).\n"
    "Не призывает к каким-либо действиям в реальной жизни.\n"
    "Ответственность за интерпретацию и применение информации лежит на читателе."
)


def _parse_message_text(text: str | None) -> str:
    raw = (text or "").strip()
    if not raw.startswith(".n"):
        return raw
    return re.sub(r"^\.n\s*", "", raw, flags=re.IGNORECASE).strip()


async def _get_self_user_id(client: TelegramClient) -> str | None:
    me = await client.get_me()
    return str(me.id) if isinstance(me, types.User) else None


def _is_message_from_self(message: types.Message, self_user_id: str | None) -> bool:
    if not self_user_id:
        return False
    sender = message.from_id
    if isinstance(sender, types.PeerUser):
        return str(sender.user_id) == self_user_id
    return False


def _add_disclaimer(text: str) -> tuple[str, list[types.TypeMessageEntity]]:
    main_text = text or ""
    separator = "\n\n" if main_text else ""
    full_text = f"{main_text}{separator}{DISCLAIMER_TEXT}"

    disclaimer_start = len(main_text) + len(separator)
    entities: list[types.TypeMessageEntity] = [
        types.MessageEntityBlockquote(
            offset=disclaimer_start,
            length=len(DISCLAIMER_TEXT),
            collapsed=True,
        )
    ]
    return full_text, entities


async def command_n(
    client: TelegramClient,
    message: types.Message,
) -> None:
    try:
        self_user_id = await _get_self_user_id(client)
        replied_message = await get_replied_message(client, message)
        message_text = _parse_message_text(message.message)

        # Case 1: /n is a reply to another message
        if replied_message and message_text == "":
            if not _is_message_from_self(replied_message, self_user_id):
                logger.warning("Cannot edit message: replied message is not from self")
                return

            replied_text = replied_message.message or ""
            full_text, entities = _add_disclaimer(replied_text)

            await client.edit_message(
                replied_message.peer_id,
                replied_message.id,
                text=full_text,
                formatting_entities=entities,
            )

            await client.delete_messages(message.peer_id, [message.id], revoke=True)
            return

        # Case 2: /n with text (edit current message)
        full_text, entities = _add_disclaimer(message_text)

        await client.edit_message(
            message.peer_id,
            message.id,
            text=full_text,
            formatting_entities=entities,
        )
    except Exception:
        logger.exception("Error handling .n")
        try:
            await client.send_message(
                message.peer_id, messages.ERROR, reply_to=message.id
            )
        except Exception:
            logger.exception("Error replying with error message")
