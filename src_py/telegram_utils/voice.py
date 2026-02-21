import os
import time

from telethon import TelegramClient
from telethon.tl import types

from src_py.telegram_utils.utils import get_peer_label

VOICES_DIR = os.path.join(os.getcwd(), "voices")


async def _ensure_voices_dir() -> None:
    os.makedirs(VOICES_DIR, exist_ok=True)


def _build_voice_filename(message: types.Message) -> str:
    peer = get_peer_label(message)
    return f"voice-{peer}-{message.id}-{int(time.time() * 1000)}.ogg"


async def _save_media(
    client: TelegramClient, message: types.Message, filename: str
) -> str:
    await _ensure_voices_dir()
    dest = os.path.join(VOICES_DIR, filename)
    await client.download_media(message, file=dest)
    return dest


async def save_voice_from_message(
    client: TelegramClient, message: types.Message
) -> str:
    return await _save_media(client, message, _build_voice_filename(message))


async def save_video_note_from_message(
    client: TelegramClient, message: types.Message
) -> str:
    peer = get_peer_label(message)
    filename = f"videonote-{peer}-{message.id}-{int(time.time() * 1000)}.mp4"
    return await _save_media(client, message, filename)
