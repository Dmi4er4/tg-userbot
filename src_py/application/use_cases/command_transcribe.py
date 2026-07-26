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
    get_replied_message,
    is_video_note,
    is_voice_message,
    reply_to,
    send_transcription_reply,
)

logger = logging.getLogger(__name__)


async def command_transcribe_voice(
    client: TelegramClient,
    message: types.Message,
    *,
    transcriber: Transcriber,
    summarizer: Summarizer | None = None,
) -> None:
    replied = await get_replied_message(client, message)
    if not replied or (not is_voice_message(replied) and not is_video_note(replied)):
        await reply_to(client, message, messages.NOT_VOICE_REPLY)
        return

    try:
        text = await transcribe_voice_message(client, replied, transcriber=transcriber)

        cleaned = text.strip()
        if not cleaned:
            await reply_to(client, message, "Расшифровка: <empty>")
            return

        summary = await build_summary(cleaned, summarizer=summarizer)
        await send_transcription_reply(client, message, cleaned, summary)
    except Exception:
        logger.exception("Error transcribing group/private convert")
        await reply_to(client, message, messages.ERROR)
