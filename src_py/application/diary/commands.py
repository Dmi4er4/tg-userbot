import logging
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient
from telethon.tl import types

from src_py.application.diary.dead_hand import DeadHand
from src_py.domain.transcriber import Transcriber, TranscribeOptions
from src_py.telegram_utils.sender_name import get_sender_display_name
from src_py.telegram_utils.utils import (
    get_replied_message,
    is_video_note,
    is_voice_message,
    reply_to,
)
from src_py.telegram_utils.voice import (
    save_video_note_from_message,
    save_voice_from_message,
)

logger = logging.getLogger(__name__)

DIARY_TAG = "#diary"
RELEASED_NOTICE = "Diary released; module disabled until restart"


MSK_TZ = timezone(timedelta(hours=3))


def _local_timestamp() -> str:
    return datetime.now(tz=MSK_TZ).strftime("%Y-%m-%d %H:%M")


def _strip_command_prefix(text: str | None) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None
    lower = raw.lower()
    if lower.startswith(".diary"):
        rest = raw[len(".diary") :].lstrip()
        return rest or None
    return None


async def command_diary(
    client: TelegramClient,
    message: types.Message,
    *,
    channel_id: object,
    dead_hand: DeadHand,
    transcriber: Transcriber,
) -> None:
    if dead_hand.is_released():
        await reply_to(client, message, RELEASED_NOTICE)
        return

    inline_text = _strip_command_prefix(message.message)
    replied = await get_replied_message(client, message)

    if not replied and not inline_text:
        await reply_to(
            client, message, "Ответьте на сообщение или напишите текст после .diary"
        )
        return

    try:
        if replied:
            await _forward_replied(client, replied, channel_id)
            if is_voice_message(replied) or is_video_note(replied):
                await _send_transcript(client, replied, channel_id, transcriber)
        if inline_text:
            await _send_inline(client, channel_id, inline_text)
        await client.delete_messages(message.peer_id, [message.id], revoke=True)
    except Exception:
        logger.exception("Error handling .diary")
        await reply_to(client, message, "Ошибка при сохранении записи дневника.")


async def _forward_replied(
    client: TelegramClient,
    replied: types.Message,
    channel_id: object,
) -> None:
    sender_name = await get_sender_display_name(client, replied)
    header = f"{DIARY_TAG} {_local_timestamp()}\nОт: {sender_name}"
    if replied.media:
        await client.send_message(channel_id, header)
        await client.forward_messages(channel_id, replied)
    else:
        lines = [header]
        if replied.message:
            lines.extend(["", replied.message])
        await client.send_message(channel_id, "\n".join(lines))


async def _send_inline(
    client: TelegramClient,
    channel_id: object,
    text: str,
) -> None:
    header = f"{DIARY_TAG} {_local_timestamp()}"
    await client.send_message(channel_id, f"{header}\n\n{text}")


async def _send_transcript(
    client: TelegramClient,
    voice_msg: types.Message,
    channel_id: object,
    transcriber: Transcriber,
) -> None:
    try:
        if is_video_note(voice_msg):
            file_path = await save_video_note_from_message(client, voice_msg)
            text = await transcriber.transcribe_file(
                file_path, "video/mp4", TranscribeOptions(language="Russian")
            )
        else:
            file_path = await save_voice_from_message(client, voice_msg)
            text = await transcriber.transcribe_ogg_file(
                file_path, TranscribeOptions(language="Russian")
            )
        cleaned = (text or "").strip()
        if not cleaned:
            logger.warning("[diary] empty transcription, skipping follow-up")
            return
        header = f"{DIARY_TAG} #transcript {_local_timestamp()}"
        await client.send_message(channel_id, f"{header}\n\n{cleaned}")
    except Exception:
        logger.exception("[diary] transcription failed; entry kept without transcript")


async def command_diary_delay(
    client: TelegramClient,
    message: types.Message,
    *,
    dead_hand: DeadHand,
) -> None:
    if dead_hand.is_released():
        await reply_to(client, message, RELEASED_NOTICE)
        return
    dead_hand.reset()
    iso = datetime.fromtimestamp(dead_hand.deadline, tz=MSK_TZ).strftime(
        "%Y-%m-%d %H:%M MSK"
    )
    try:
        await reply_to(client, message, f"Diary deadline → {iso}")
    finally:
        try:
            await client.delete_messages(message.peer_id, [message.id], revoke=True)
        except Exception:
            logger.exception("[diary] failed to delete .diary-delay command")
