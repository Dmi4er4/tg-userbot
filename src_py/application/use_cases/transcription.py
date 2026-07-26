import logging

from telethon import TelegramClient
from telethon.tl import types

from src_py.domain.summarizer import Summarizer
from src_py.domain.transcriber import Transcriber, TranscribeOptions
from src_py.telegram_utils.utils import is_video_note
from src_py.telegram_utils.voice import (
    save_video_note_from_message,
    save_voice_from_message,
)

logger = logging.getLogger(__name__)

# Below this length a TL;DR costs more attention than it saves.
SUMMARY_MIN_CHARS = 600


async def transcribe_voice_message(
    client: TelegramClient,
    message: types.Message,
    *,
    transcriber: Transcriber,
) -> str:
    """Download a voice message / video note and return its transcript."""
    if is_video_note(message):
        file_path = await save_video_note_from_message(client, message)
        return await transcriber.transcribe_file(
            file_path, "video/mp4", TranscribeOptions(language="Russian")
        )

    file_path = await save_voice_from_message(client, message)
    return await transcriber.transcribe_ogg_file(
        file_path, TranscribeOptions(language="Russian")
    )


async def build_summary(
    transcript: str,
    *,
    summarizer: Summarizer | None,
    min_chars: int = SUMMARY_MIN_CHARS,
) -> str | None:
    if summarizer is None or len(transcript) < min_chars:
        return None
    try:
        return await summarizer.summarize(transcript)
    except Exception:
        logger.exception("Summarization failed")
        return None
