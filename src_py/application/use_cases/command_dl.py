import asyncio
import logging
import os
import re
import tempfile

from telethon import TelegramClient
from telethon.tl import types

from src_py.telegram_utils.utils import get_replied_message, reply_to

logger = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://\S+")

# Telegram allows 2 GB per file for regular accounts; stay well below it so a
# stray 4K stream cannot stall the bot for an hour.
MAX_FILESIZE_BYTES = 512 * 1024 * 1024
MAX_HEIGHT = 1080

USAGE = "Использование: `.dl <url>` — видео, `.dl -a <url>` — только аудио (mp3)."

AUDIO_FLAGS = {"-a", "-audio", "audio", "mp3"}


def _extract_url(message: types.Message | None) -> str | None:
    if message is None:
        return None

    text = message.message or ""
    for ent in message.entities or []:
        if isinstance(ent, types.MessageEntityTextUrl):
            return ent.url
        if isinstance(ent, types.MessageEntityUrl):
            return text[ent.offset : ent.offset + ent.length]

    match = URL_RE.search(text)
    return match.group(0) if match else None


def _wants_audio(text: str | None) -> bool:
    parts = (text or "").strip().split()
    return any(p.lower() in AUDIO_FLAGS for p in parts[1:])


def _build_options(target_dir: str, audio_only: bool, cookies_file: str) -> dict:
    options: dict = {
        "outtmpl": os.path.join(target_dir, "%(title).80s.%(ext)s"),
        "restrictfilenames": True,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "max_filesize": MAX_FILESIZE_BYTES,
        "retries": 3,
        "socket_timeout": 30,
    }
    if cookies_file:
        options["cookiefile"] = cookies_file

    if audio_only:
        options["format"] = "bestaudio/best"
        options["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ]
    else:
        options["format"] = (
            f"bv*[height<={MAX_HEIGHT}][ext=mp4]+ba[ext=m4a]/"
            f"b[height<={MAX_HEIGHT}][ext=mp4]/"
            f"bv*[height<={MAX_HEIGHT}]+ba/b"
        )
        options["merge_output_format"] = "mp4"

    return options


def _download(url: str, target_dir: str, audio_only: bool, cookies_file: str) -> dict:
    import yt_dlp

    with yt_dlp.YoutubeDL(_build_options(target_dir, audio_only, cookies_file)) as ydl:
        return ydl.extract_info(url, download=True) or {}


def _pick_downloaded_file(target_dir: str) -> str | None:
    candidates = [
        os.path.join(target_dir, name)
        for name in os.listdir(target_dir)
        if os.path.isfile(os.path.join(target_dir, name))
    ]
    if not candidates:
        return None
    return max(candidates, key=os.path.getsize)


def _build_attributes(
    info: dict, file_path: str, audio_only: bool
) -> list[types.TypeDocumentAttribute]:
    duration = int(info.get("duration") or 0)
    filename = os.path.basename(file_path)

    if audio_only:
        return [
            types.DocumentAttributeAudio(
                duration=duration,
                title=info.get("title") or filename,
                performer=info.get("uploader") or info.get("channel") or None,
            ),
            types.DocumentAttributeFilename(filename),
        ]

    return [
        types.DocumentAttributeVideo(
            duration=duration,
            w=int(info.get("width") or 0),
            h=int(info.get("height") or 0),
            supports_streaming=True,
        ),
        types.DocumentAttributeFilename(filename),
    ]


async def command_dl(
    client: TelegramClient,
    message: types.Message,
    *,
    cookies_file: str = "",
) -> None:
    url = _extract_url(message)
    if not url:
        replied = await get_replied_message(client, message)
        url = _extract_url(replied)
    if not url:
        await reply_to(client, message, USAGE)
        return

    audio_only = _wants_audio(message.message)
    status = await client.send_message(
        message.peer_id, "⏳ Скачиваю…", reply_to=message.id
    )

    with tempfile.TemporaryDirectory(prefix="tgdl-") as target_dir:
        try:
            info = await asyncio.to_thread(
                _download, url, target_dir, audio_only, cookies_file
            )
        except Exception as exc:
            logger.exception("yt-dlp download failed for %s", url)
            await client.edit_message(status, f"Не удалось скачать: {exc}")
            return

        file_path = _pick_downloaded_file(target_dir)
        if not file_path:
            await client.edit_message(
                status,
                "Ничего не скачалось "
                f"(возможно, файл больше {MAX_FILESIZE_BYTES // (1024 * 1024)} МБ).",
            )
            return

        try:
            await client.send_file(
                message.peer_id,
                file_path,
                reply_to=message.id,
                caption=(info.get("title") or "")[:1024],
                force_document=False,
                attributes=_build_attributes(info, file_path, audio_only),
            )
        except Exception:
            logger.exception("Failed to send downloaded file")
            await client.edit_message(status, "Скачалось, но не отправилось.")
            return

    try:
        await client.delete_messages(message.peer_id, [status.id])
    except Exception:
        logger.exception("Failed to delete .dl status message")
