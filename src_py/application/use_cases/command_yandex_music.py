import logging
import os
import re
import tempfile

from telethon import TelegramClient
from telethon.tl import types
from yandex_music import ClientAsync

from src_py.telegram_utils.utils import reply_to

logger = logging.getLogger(__name__)

TRACK_URL_RE = re.compile(r"music\.yandex\.(?:ru|com|by|kz|uz)/album/(\d+)/track/(\d+)")


def _parse_track_ids(text: str | None) -> tuple[str, str] | None:
    if not text:
        return None
    m = TRACK_URL_RE.search(text)
    if not m:
        return None
    return m.group(1), m.group(2)


def _extract_track_ids(message: types.Message) -> tuple[str, str] | None:
    result = _parse_track_ids(message.message)
    if result:
        return result
    for ent in message.entities or []:
        if isinstance(ent, types.MessageEntityTextUrl):
            result = _parse_track_ids(ent.url)
            if result:
                return result
        elif isinstance(ent, types.MessageEntityUrl):
            url = (message.message or "")[ent.offset : ent.offset + ent.length]
            result = _parse_track_ids(url)
            if result:
                return result
    return None


async def command_yandex_music(
    client: TelegramClient,
    message: types.Message,
    *,
    yandex_music_token: str,
) -> None:
    ids = _extract_track_ids(message)
    if not ids:
        await reply_to(client, message, "Использование: .ym <ссылка на трек Яндекс Музыки>")
        return

    album_id, track_id = ids

    if not yandex_music_token:
        await reply_to(client, message, "YANDEX_MUSIC_TOKEN не настроен.")
        return

    tmp_path = None
    try:
        ym = ClientAsync(yandex_music_token)
        await ym.init()

        tracks = await ym.tracks([f"{track_id}:{album_id}"])
        if not tracks:
            await reply_to(client, message, "Трек не найден.")
            return

        track = tracks[0]
        title = track.title or "Unknown"
        artists = ", ".join(a.name for a in (track.artists or []) if a.name) or "Unknown"

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mp3")
        os.close(tmp_fd)

        await track.download_async(tmp_path, codec="mp3", bitrate_in_kbps=320)

        duration = (track.duration_ms or 0) // 1000

        await client.send_file(
            message.peer_id,
            tmp_path,
            reply_to=message.id,
            voice=False,
            attributes=[
                types.DocumentAttributeAudio(
                    duration=duration,
                    title=title,
                    performer=artists,
                )
            ],
        )
    except Exception:
        logger.exception("Error downloading Yandex Music track")
        await reply_to(client, message, "Ошибка при скачивании трека.")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
