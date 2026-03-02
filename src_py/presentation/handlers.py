from dataclasses import dataclass
from typing import Awaitable, Callable

from telethon import TelegramClient
from telethon.tl import types

from src_py.application.use_cases.command_ai import command_ai
from src_py.application.use_cases.command_google import command_google
from src_py.application.use_cases.command_yandex_music import command_yandex_music
from src_py.application.use_cases.command_id import command_id
from src_py.application.use_cases.command_n import command_n
from src_py.application.use_cases.command_save import command_save
from src_py.application.use_cases.command_screenshot import command_screenshot
from src_py.application.use_cases.command_sticker import command_sticker_to_photo
from src_py.application.use_cases.command_transcribe import command_transcribe_voice
from src_py.application.use_cases.command_wiki import command_wiki
from src_py.application.use_cases.disappearing_media import forward_disappearing_media, is_disappearing_media
from src_py.application.use_cases.private_transcribe import private_transcribe_voice
from src_py.domain.transcriber import Transcriber
from src_py.telegram_utils.utils import get_peer_id, is_private_peer, is_video_note, is_voice_message


@dataclass
class Handler:
    name: str
    is_triggered: Callable[
        [TelegramClient, types.Message, str | None], Awaitable[bool]
    ]
    handle: Callable[[TelegramClient, types.Message], Awaitable[None]]


def _is_sender_self(message: types.Message, self_user_id: str | None) -> bool:
    if not self_user_id:
        return False
    sender = message.from_id
    if isinstance(sender, types.PeerUser):
        return str(sender.user_id) == self_user_id
    return False


def create_handlers(
    *,
    transcriber: Transcriber,
    channel_id: object,
    auto_transcribe_peer_ids: set[str],
    transcribe_disabled_peer_ids: set[str],
    yandex_music_token: str = "",
    eliza_bot_username: str | None = None,
) -> list[Handler]:
    handlers = [
        Handler(
            name="Disappearing media auto-save",
            is_triggered=lambda _c, msg, _s: _disappearing_trigger(msg),
            handle=lambda c, msg: forward_disappearing_media(
                c, msg, channel_id=channel_id
            ),
        ),
        Handler(
            name="Private auto voice/videonote",
            is_triggered=lambda _c, msg, _s: _auto_voice_trigger(
                msg, auto_transcribe_peer_ids, transcribe_disabled_peer_ids
            ),
            handle=lambda c, msg: private_transcribe_voice(
                c, msg, transcriber=transcriber
            ),
        ),
        Handler(
            name="Command .convert",
            is_triggered=lambda _c, msg, s: _self_command_trigger(msg, s, ".convert"),
            handle=lambda c, msg: command_transcribe_voice(
                c, msg, transcriber=transcriber
            ),
        ),
        Handler(
            name="Command .save",
            is_triggered=lambda _c, msg, s: _self_command_trigger(msg, s, ".save"),
            handle=lambda c, msg: command_save(c, msg, channel_id=channel_id),
        ),
        Handler(
            name="Command .id",
            is_triggered=lambda _c, msg, s: _self_command_trigger(msg, s, ".id"),
            handle=lambda c, msg: command_id(c, msg),
        ),
        Handler(
            name="Command .sticker",
            is_triggered=lambda _c, msg, s: _self_command_trigger(msg, s, ".sticker"),
            handle=lambda c, msg: command_sticker_to_photo(c, msg),
        ),
        Handler(
            name="Command .ss",
            is_triggered=lambda _c, msg, s: _self_command_trigger(msg, s, ".ss"),
            handle=lambda c, msg: command_screenshot(c, msg),
        ),
        Handler(
            name="Command .w",
            is_triggered=lambda _c, msg, s: _self_command_trigger(msg, s, ".w"),
            handle=lambda c, msg: command_wiki(c, msg),
        ),
        Handler(
            name="Command .g",
            is_triggered=lambda _c, msg, s: _self_command_trigger(msg, s, ".g"),
            handle=lambda c, msg: command_google(c, msg),
        ),
        Handler(
            name="Command .n",
            is_triggered=lambda _c, msg, s: _self_command_trigger(msg, s, ".n"),
            handle=lambda c, msg: command_n(c, msg),
        ),
    ]

    if eliza_bot_username is not None:
        handlers.append(
            Handler(
                name="Command .ai",
                is_triggered=lambda _c, msg, s: _self_command_trigger(msg, s, ".ai"),
                handle=lambda c, msg: command_ai(
                    c, msg, bot_username=eliza_bot_username
                ),
            ),
        )

    handlers.append(
        Handler(
            name="Command .ym",
            is_triggered=lambda _c, msg, s: _self_command_trigger(msg, s, ".ym"),
            handle=lambda c, msg: command_yandex_music(
                c, msg, yandex_music_token=yandex_music_token
            ),
        ),
    )

    return handlers


async def _disappearing_trigger(message: types.Message) -> bool:
    return is_disappearing_media(message)


async def _auto_voice_trigger(
    message: types.Message,
    auto_ids: set[str],
    disabled_ids: set[str],
) -> bool:
    if not is_voice_message(message) and not is_video_note(message):
        return False
    peer_id = get_peer_id(message)
    if peer_id and peer_id in disabled_ids:
        return False
    return is_private_peer(message.peer_id) or (bool(peer_id) and peer_id in auto_ids)


async def _self_command_trigger(
    message: types.Message, self_user_id: str | None, prefix: str
) -> bool:
    if not _is_sender_self(message, self_user_id):
        return False
    text = (message.message or "").strip()
    return text.startswith(prefix)
