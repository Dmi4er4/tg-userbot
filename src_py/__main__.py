import asyncio
import logging
import signal
import sys

from dotenv import load_dotenv

load_dotenv()

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl import types

from src_py.config import settings
from src_py.impl.speech_recognition_transcriber import SpeechRecognitionTranscriber
from src_py.impl.groq_whisper_transcriber import GroqWhisperTranscriber
from src_py.presentation.bot import TgUserbot
from src_py.presentation.handlers import create_handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _login() -> None:
    api_id = int(input("TG_API_ID: ").strip())
    api_hash = input("TG_API_HASH: ").strip()

    client = TelegramClient(
        StringSession(),
        api_id,
        api_hash,
        device_model="Samsung Galaxy S24",
        system_version="Android 14",
        app_version="10.14.5",
        lang_code="ru",
        system_lang_code="ru-RU",
    )
    await client.start()

    session_str = client.session.save()

    print("\n\nAdd these to your .env file:\n")
    print(f"TG_API_ID={api_id}")
    print(f"TG_API_HASH={api_hash}")
    print(f"TG_SESSION={session_str}")

    await client.disconnect()


async def _resolve_userbot_target(
    client: TelegramClient, configured_channel_id: int
) -> object:
    normalized = configured_channel_id
    raw_id = int(str(abs(normalized)).removeprefix("100"))

    candidates: list[object] = [
        normalized,
        raw_id,
        types.PeerChannel(raw_id),
        types.PeerChat(raw_id),
        types.PeerUser(raw_id),
    ]
    for candidate in candidates:
        try:
            return await client.get_input_entity(candidate)
        except Exception:
            continue

    marked_channel_id = int(f"-100{raw_id}")

    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if not isinstance(entity, (types.Channel, types.Chat, types.User)):
            continue
        if dialog.id in {normalized, raw_id, marked_channel_id}:
            return await client.get_input_entity(entity)

    logger.warning(
        "Cannot resolve channel_id=%s; using Saved Messages",
        configured_channel_id,
    )
    return "me"


async def _run() -> None:
    client = TelegramClient(
        StringSession(settings.tg_session), settings.tg_api_id, settings.tg_api_hash
    )
    client.flood_sleep_threshold = 60
    await client.start()

    logger.info("Userbot started")

    channel_id = settings.get_userbot_channel_id()
    if channel_id is not None:
        userbot_target = await _resolve_userbot_target(client, channel_id)
    else:
        logger.info("USERBOT_CHANNEL_ID not set; using Saved Messages")
        userbot_target = "me"

    if settings.groq_api_key:
        transcriber = GroqWhisperTranscriber(settings.groq_api_key)
        logger.info("Using Groq Whisper API for transcription")
    else:
        transcriber = SpeechRecognitionTranscriber()
        logger.info("GROQ_API_KEY not set; using Google Speech Recognition")

    handlers = create_handlers(
        transcriber=transcriber,
        channel_id=userbot_target,
        auto_transcribe_peer_ids=settings.get_auto_transcribe_peer_ids(),
        transcribe_disabled_peer_ids=settings.get_transcribe_disabled_peer_ids(),
        yandex_music_token=settings.yandex_music_token,
    )

    bot = TgUserbot(
        client,
        handlers,
        deleted_tracker_enabled=settings.deleted_tracker_enabled,
        channel_id=userbot_target,
    )
    await bot.start()

    logger.info("Bot is running. Press Ctrl+C to stop.")
    await client.run_until_disconnected()


def _handle_signal(sig: int, _frame) -> None:
    logger.info("Received signal %s, shutting down", sig)
    sys.exit(0)


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)

if len(sys.argv) > 1 and sys.argv[1] == "login":
    asyncio.run(_login())
else:
    asyncio.run(_run())
