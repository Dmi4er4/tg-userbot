import logging

from telethon import TelegramClient
from telethon.tl import types

from src_py import messages
from src_py.domain.transcriber import Transcriber, TranscribeOptions
from src_py.telegram_utils.utils import get_replied_message, is_video_note, is_voice_message, reply_to
from src_py.telegram_utils.voice import save_video_note_from_message, save_voice_from_message

logger = logging.getLogger(__name__)


async def command_transcribe_voice(
    client: TelegramClient,
    message: types.Message,
    *,
    transcriber: Transcriber,
) -> None:
    replied = await get_replied_message(client, message)
    if not replied or (not is_voice_message(replied) and not is_video_note(replied)):
        await reply_to(client, message, messages.NOT_VOICE_REPLY)
        return

    try:
        if is_video_note(replied):
            file_path = await save_video_note_from_message(client, replied)
            text = await transcriber.transcribe_file(
                file_path, "video/mp4", TranscribeOptions(language="Russian")
            )
        else:
            file_path = await save_voice_from_message(client, replied)
            text = await transcriber.transcribe_ogg_file(
                file_path, TranscribeOptions(language="Russian")
            )

        cleaned = text.strip()
        if cleaned:
            await reply_to(client, message, f"Расшифровка:\n{cleaned}")
        else:
            await reply_to(client, message, "Расшифровка: <empty>")
    except Exception:
        logger.exception("Error transcribing group/private convert")
        await reply_to(client, message, messages.ERROR)
