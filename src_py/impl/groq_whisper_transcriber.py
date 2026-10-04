import asyncio
import io
import logging
import math
import os
import re
import time
from pathlib import Path

import aiohttp
from pydub import AudioSegment
from pydub.silence import detect_silence

from src_py.domain.transcriber import TranscribeOptions

logger = logging.getLogger(__name__)

LANGUAGE_MAP = {
    "Russian": "ru",
    "English": "en",
}

GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MODEL = "whisper-large-v3-turbo"
TRANSCRIPTION_ERROR = "(ошибка транскрибации)"
CHUNK_TARGET_MS = 60_000
CHUNK_BOUNDARY_WINDOW_MS = 10_000
MIN_CHUNK_MS = 15_000
MAX_CONCURRENT_CHUNKS = 3
MAX_API_ATTEMPTS = 3

# Known Whisper hallucination patterns (appears on silence / short audio)
# Sources:
#   https://gist.github.com/waveletdeboshir/8bf52f04bf78018194f25b2390c08309
#   https://github.com/openai/whisper/discussions/2131
#   https://huggingface.co/datasets/sachaarbonel/whisper-hallucinations
_HALLUCINATION_PATTERNS: list[re.Pattern[str]] = [
    # Subtitle credits
    re.compile(r"Субтитры\s*(сделал|делал|создал|создавал|подготовил|подогнал)\s*\S*", re.IGNORECASE),
    re.compile(r"Редактор субтитров.{0,30}", re.IGNORECASE),
    re.compile(r"Спасибо за субтитры!?", re.IGNORECASE),
    # Subscribe / like / watch
    re.compile(r"Подпиши(сь|тесь)\s*(на\s*(канал|мой канал))?[.!]?", re.IGNORECASE),
    re.compile(r"Подписывайтесь\s*(на\s*(канал|мой канал))?[.!]?", re.IGNORECASE),
    re.compile(r"Ставь(те)?\s*лайк.{0,20}", re.IGNORECASE),
    # Thanks for watching
    re.compile(r"(Благодарю|Спасибо)\s*за\s*(просмотр|внимание)[.!]?", re.IGNORECASE),
    re.compile(r"Thanks?\s*for\s*watching[.!]?", re.IGNORECASE),
    re.compile(r"Thank\s*you\s*for\s*watching[.!]?", re.IGNORECASE),
    # Continuation
    re.compile(r"Продолжение следует\.{0,3}", re.IGNORECASE),
    re.compile(r"Смотрите продолжение[.!]?", re.IGNORECASE),
    # Music/sound stage directions (caps in brackets or without)
    re.compile(r"\(?[А-ЯЁ]{2,}\s+МУЗЫКА\)?", re.IGNORECASE),
    re.compile(r"\(?(АПЛОДИСМЕНТЫ|СМЕХ|ВЫСТРЕЛЫ?|ВЗРЫВ|ПЕРЕСТРЕЛКА|КАШЕЛЬ)\)?", re.IGNORECASE),
    # English subtitle credit artifacts
    re.compile(r"subtitles\s*(by|created by)\s*.{0,30}", re.IGNORECASE),
    re.compile(r"amara\.?org", re.IGNORECASE),
]


def _strip_hallucinations(text: str) -> str:
    result = text
    for pat in _HALLUCINATION_PATTERNS:
        result = pat.sub("", result)
    return result.strip()


def _split_audio(audio: AudioSegment) -> list[AudioSegment]:
    """Split long audio near pauses without dropping or repeating any samples."""
    chunk_count = math.ceil(len(audio) / CHUNK_TARGET_MS)
    if chunk_count <= 1:
        return [audio]

    dbfs = audio.dBFS
    silence_threshold = dbfs - 16 if math.isfinite(dbfs) else -40
    chunks: list[AudioSegment] = []
    start = 0

    for index in range(1, chunk_count):
        target = round(len(audio) * index / chunk_count)
        left = max(start + MIN_CHUNK_MS, target - CHUNK_BOUNDARY_WINDOW_MS)
        right = min(
            len(audio) - (chunk_count - index) * MIN_CHUNK_MS,
            target + CHUNK_BOUNDARY_WINDOW_MS,
        )
        cut = target
        if right - left >= 250:
            silences = detect_silence(
                audio[left:right],
                min_silence_len=250,
                silence_thresh=silence_threshold,
                seek_step=20,
            )
            if silences:
                cut = min(
                    (left + (begin + end) // 2 for begin, end in silences),
                    key=lambda position: abs(position - target),
                )
            else:
                # Continuous speech or background noise: cut at the quietest
                # quarter-second near the target instead of an arbitrary word.
                quietest = min(
                    range(left, right - 249, 100),
                    key=lambda position: (
                        audio[position : position + 250].rms,
                        abs(position + 125 - target),
                    ),
                )
                cut = quietest + 125
        chunks.append(audio[start:cut])
        start = cut

    chunks.append(audio[start:])
    return chunks


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

        started = time.perf_counter()
        audio_chunks = await asyncio.to_thread(
            self._prepare_audio_chunks, file_path, mime_type
        )
        if len(audio_chunks) == 1:
            return await self._call_groq_api(audio_chunks[0], lang, opts.prompt)

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHUNKS)

        async def transcribe_chunk(audio_bytes: bytes) -> str:
            async with semaphore:
                return await self._call_groq_api(audio_bytes, lang, opts.prompt)

        texts = await asyncio.gather(
            *(transcribe_chunk(audio_bytes) for audio_bytes in audio_chunks)
        )
        if TRANSCRIPTION_ERROR in texts:
            return TRANSCRIPTION_ERROR
        logger.info(
            "Transcribed %d chunks in %.1fs",
            len(audio_chunks),
            time.perf_counter() - started,
        )
        return " ".join(text.strip() for text in texts if text.strip())

    def _prepare_audio_chunks(self, file_path: str, mime_type: str) -> list[bytes]:
        fmt = self._mime_to_format(mime_type)
        audio = AudioSegment.from_file(file_path, format=fmt)
        chunks = _split_audio(audio)
        if len(chunks) > 1:
            logger.info("Transcribing %.1fs audio in %d chunks", len(audio) / 1000, len(chunks))
        encoded = []
        for chunk in chunks:
            buf = io.BytesIO()
            chunk.export(buf, format="mp3", bitrate="64k")
            encoded.append(buf.getvalue())
        return encoded

    async def _call_groq_api(
        self, audio_bytes: bytes, lang: str, prompt: str | None
    ) -> str:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for attempt in range(MAX_API_ATTEMPTS):
                # FormData is consumed by a request, so retries need a fresh one.
                data = aiohttp.FormData()
                data.add_field(
                    "file", audio_bytes, filename="audio.mp3", content_type="audio/mpeg"
                )
                data.add_field("model", MODEL)
                data.add_field("language", lang)
                data.add_field("response_format", "text")
                if prompt:
                    data.add_field("prompt", prompt)

                async with session.post(
                    GROQ_TRANSCRIPTION_URL, headers=headers, data=data
                ) as resp:
                    if resp.status == 200:
                        return _strip_hallucinations(await resp.text())

                    body = await resp.text()
                    retryable = resp.status == 429 or 500 <= resp.status < 600
                    if not retryable or attempt == MAX_API_ATTEMPTS - 1:
                        logger.error("Groq API error %s: %s", resp.status, body)
                        return TRANSCRIPTION_ERROR

                    delay = float(2**attempt)
                    if resp.status == 429:
                        try:
                            delay = float(resp.headers.get("Retry-After", delay))
                        except ValueError:
                            pass
                    delay = min(max(delay, 1.0), 120.0)
                    logger.warning(
                        "Groq API returned %s; retrying in %.1fs", resp.status, delay
                    )
                await asyncio.sleep(delay)

        return TRANSCRIPTION_ERROR

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
