import logging

from telethon import TelegramClient
from telethon.tl import types
from telethon.tl.functions.messages import MarkDialogUnreadRequest

from src_py import messages
from src_py.domain.transcriber import Transcriber, TranscribeOptions
from src_py.telegram_utils.utils import is_video_note, is_voice_message, reply_to
from src_py.telegram_utils.voice import save_video_note_from_message, save_voice_from_message

logger = logging.getLogger(__name__)


async def private_transcribe_voice(
    client: TelegramClient,
    message: types.Message,
    *,
    transcriber: Transcriber,
) -> None:
    if not is_voice_message(message) and not is_video_note(message):
        return

    try:
        if is_video_note(message):
            file_path = await save_video_note_from_message(client, message)
            text = await transcriber.transcribe_file(
                file_path, "video/mp4", TranscribeOptions(language="Russian")
            )
        else:
            file_path = await save_voice_from_message(client, message)
            text = await transcriber.transcribe_ogg_file(
                file_path, TranscribeOptions(language="Russian")
            )

        cleaned = text.strip()
        if cleaned:
            await reply_to(client, message, f"Расшифровка:\n{cleaned}")
        else:
            await reply_to(client, message, "Расшифровка: <empty>")

        try:
            await client(MarkDialogUnreadRequest(
                peer=message.peer_id,
                unread=True,
            ))
        except Exception:
            logger.exception("Failed to mark dialog as unread")
    except Exception:
        logger.exception("Error transcribing private voice/videonote")
        await reply_to(client, message, messages.ERROR)
