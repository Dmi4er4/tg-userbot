from telethon import TelegramClient
from telethon.tl import types

from src_py import messages

TELEGRAM_MAX_MESSAGE_LENGTH = 4096
PREFIX_LENGTH = len(messages.USERBOT_MARK) + 1  # mark + \n
MAX_TEXT_LENGTH = TELEGRAM_MAX_MESSAGE_LENGTH - PREFIX_LENGTH


def is_voice_message(message: types.Message) -> bool:
    media = message.media
    if not isinstance(media, types.MessageMediaDocument):
        return False
    doc = media.document
    if not isinstance(doc, types.Document):
        return False
    for attr in doc.attributes or []:
        if isinstance(attr, types.DocumentAttributeAudio) and attr.voice:
            return True
    mime = (doc.mime_type or "").lower()
    return mime == "audio/ogg"


def is_video_note(message: types.Message) -> bool:
    media = message.media
    if not isinstance(media, types.MessageMediaDocument):
        return False
    doc = media.document
    if not isinstance(doc, types.Document):
        return False
    for attr in doc.attributes or []:
        if isinstance(attr, types.DocumentAttributeVideo) and attr.round_message:
            return True
    return False


def is_private_peer(peer: types.TypePeer | None) -> bool:
    return isinstance(peer, types.PeerUser)


def is_group_peer(peer: types.TypePeer | None) -> bool:
    return isinstance(peer, (types.PeerChat, types.PeerChannel))


def get_peer_label(message: types.Message) -> str:
    p = message.peer_id
    if isinstance(p, types.PeerUser):
        return f"user-{p.user_id}"
    if isinstance(p, types.PeerChat):
        return f"chat-{p.chat_id}"
    if isinstance(p, types.PeerChannel):
        return f"channel-{p.channel_id}"
    return "unknown"


def get_sender_user_id(message: types.Message) -> str | None:
    f = message.from_id
    if isinstance(f, types.PeerUser):
        return str(f.user_id)
    return None


def get_peer_id(message: types.Message) -> str | None:
    p = message.peer_id
    if isinstance(p, types.PeerUser):
        return str(p.user_id)
    if isinstance(p, types.PeerChat):
        return str(p.chat_id)
    if isinstance(p, types.PeerChannel):
        return str(p.channel_id)
    return None


async def get_replied_message(
    client: TelegramClient, message: types.Message
) -> types.Message | None:
    reply_to = message.reply_to
    if not reply_to or not getattr(reply_to, "reply_to_msg_id", None):
        return None
    replied_msg_id = reply_to.reply_to_msg_id
    fetched = await client.get_messages(message.peer_id, ids=replied_msg_id)
    if isinstance(fetched, list):
        fetched = fetched[0] if fetched else None
    return fetched if isinstance(fetched, types.Message) else None


def _split_text(text: str) -> list[str]:
    if len(text) <= MAX_TEXT_LENGTH:
        return [text]

    chunks: list[str] = []
    remaining = text

    while len(remaining) > MAX_TEXT_LENGTH:
        split_index = remaining.rfind("\n", 0, MAX_TEXT_LENGTH)
        if split_index == -1 or split_index < MAX_TEXT_LENGTH * 0.5:
            split_index = remaining.rfind(" ", 0, MAX_TEXT_LENGTH)
        if split_index == -1 or split_index < MAX_TEXT_LENGTH * 0.5:
            split_index = MAX_TEXT_LENGTH

        chunks.append(remaining[:split_index].rstrip())
        remaining = remaining[split_index:].lstrip()

    if remaining:
        chunks.append(remaining)

    return chunks


async def reply_to(
    client: TelegramClient, message: types.Message, text: str
) -> None:
    await send_formatted_reply(
        client, message.peer_id, text, reply_to_msg_id=message.id
    )


async def send_formatted_reply(
    client: TelegramClient,
    peer: object,
    text: str,
    reply_to_msg_id: int | None = None,
) -> None:
    chunks = _split_text(text)

    for i, chunk in enumerate(chunks):
        final_text = f"{messages.USERBOT_MARK}\n{chunk}"

        entities = [
            types.MessageEntityBlockquote(
                offset=len(messages.USERBOT_MARK) + 1,
                length=len(final_text) - len(messages.USERBOT_MARK) - 1,
                collapsed=True,
            )
        ]

        await client.send_message(
            peer,
            final_text,
            reply_to=reply_to_msg_id if i == 0 else None,
            formatting_entities=entities,
        )
