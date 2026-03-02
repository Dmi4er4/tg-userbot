import asyncio
import io
import logging
import os
import re
from pathlib import Path

import aiohttp
from pydub import AudioSegment

from src_py.domain.transcriber import TranscribeOptions

logger = logging.getLogger(__name__)

LANGUAGE_MAP = {
    "Russian": "ru",
    "English": "en",
}

GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MODEL = "whisper-large-v3-turbo"

# Known Whisper hallucination patterns (appears on silence / short audio)
_HALLUCINATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"Продолжение следует\.{0,3}", re.IGNORECASE),
    re.compile(r"Субтитры\s*(сделал|делал|создал|подготовил)\s*\S*", re.IGNORECASE),
    re.compile(r"Редактор субтитров.{0,30}", re.IGNORECASE),
    re.compile(r"Благодарю за просмотр\.?", re.IGNORECASE),
    re.compile(r"Подписывайтесь на канал\.?", re.IGNORECASE),
]


def _strip_hallucinations(text: str) -> str:
    result = text
    for pat in _HALLUCINATION_PATTERNS:
        result = pat.sub("", result)
    return result.strip()


class GroqWhisperTranscriber:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def transcribe_ogg_file(
        self, file_path: str, options: TranscribeOptions | None = None
    ) -> str:
        return await self.transcribe_file(file_path, "audio/ogg", options)

    async def transcribe_file(
        self, file_path: str, mime_type: str, options: TranscribeOptions | None = None
    ) -> str:
        opts = options or TranscribeOptions()
        lang = LANGUAGE_MAP.get(opts.language, "ru")

        audio_bytes = await asyncio.to_thread(self._prepare_audio, file_path, mime_type)
        return await self._call_groq_api(audio_bytes, lang, opts.prompt)

    def _prepare_audio(self, file_path: str, mime_type: str) -> bytes:
        fmt = self._mime_to_format(mime_type)
        segment = AudioSegment.from_file(file_path, format=fmt)
        buf = io.BytesIO()
        segment.export(buf, format="mp3", bitrate="64k")
        return buf.getvalue()

    async def _call_groq_api(
        self, audio_bytes: bytes, lang: str, prompt: str | None
    ) -> str:
        data = aiohttp.FormData()
        data.add_field(
            "file", audio_bytes, filename="audio.mp3", content_type="audio/mpeg"
        )
        data.add_field("model", MODEL)
        data.add_field("language", lang)
        data.add_field("response_format", "text")
        if prompt:
            data.add_field("prompt", prompt)

        headers = {"Authorization": f"Bearer {self._api_key}"}

        async with aiohttp.ClientSession() as session:
            async with session.post(
                GROQ_TRANSCRIPTION_URL, headers=headers, data=data
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error("Groq API error %s: %s", resp.status, body)
                    return "(ошибка транскрибации)"
                text = await resp.text()
                return _strip_hallucinations(text)

    @staticmethod
    def _mime_to_format(mime_type: str) -> str:
        mapping = {
            "audio/ogg": "ogg",
            "audio/mpeg": "mp3",
            "audio/mp4": "mp4",
            "audio/wav": "wav",
            "video/mp4": "mp4",
        }
        return mapping.get(mime_type, mime_type.split("/")[-1])
