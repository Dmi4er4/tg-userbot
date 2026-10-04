import logging

from telethon import TelegramClient
from telethon.tl import types

from src_py import messages
from src_py.application.use_cases.transcription import (
    build_summary,
    transcribe_voice_message,
)
from src_py.domain.summarizer import Summarizer
from src_py.domain.transcriber import Transcriber
from src_py.telegram_utils.utils import (
    is_video_note,
    is_voice_message,
    reply_to,
    send_transcription_reply,
)

logger = logging.getLogger(__name__)

NO_TRANSCRIPT_RESULTS = frozenset({
    "(ошибка транскрибации)",
    "(не удалось распознать речь)",
})


async def private_transcribe_voice(
    client: TelegramClient,
    message: types.Message,
    *,
    transcriber: Transcriber,
    summarizer: Summarizer | None = None,
) -> bool:
    if not is_voice_message(message) and not is_video_note(message):
        return False

    try:
        text = await transcribe_voice_message(client, message, transcriber=transcriber)

        cleaned = text.strip()
        if not cleaned:
            return False

        if cleaned in NO_TRANSCRIPT_RESULTS:
            await send_transcription_reply(client, message, cleaned)
            return False

        summary = await build_summary(cleaned, summarizer=summarizer)
        await send_transcription_reply(client, message, cleaned, summary)
        return True
    except Exception:
        logger.exception("Error transcribing private voice/videonote")
        await reply_to(client, message, messages.ERROR)
        return False
