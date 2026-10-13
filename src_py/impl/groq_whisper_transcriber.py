import asyncio
import io
import logging
import math
import time
from dataclasses import dataclass

import aiohttp
from pydub import AudioSegment
from pydub.silence import detect_silence

from src_py.domain.transcriber import TranscribeOptions
from src_py.impl.speech_activity import SileroSpeechDetector, SpeechActivity
from src_py.impl.transcription_filter import filter_transcription
from src_py.impl.transcription_artifacts import strip_boilerplate

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


@dataclass(frozen=True)
class AudioChunk:
    data: bytes
    activity: SpeechActivity


class GroqWhisperTranscriber:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._speech_detector = SileroSpeechDetector()

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
        if not audio_chunks:
            return ""
        if len(audio_chunks) == 1:
            return await self._transcribe_chunk(audio_chunks[0], lang, opts.prompt)

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHUNKS)

        async def transcribe_chunk(chunk: AudioChunk) -> str:
            async with semaphore:
                return await self._transcribe_chunk(chunk, lang, opts.prompt)

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
        return strip_boilerplate(" ".join(text.strip() for text in texts if text.strip()))

    async def _transcribe_chunk(
        self, chunk: AudioChunk, lang: str, prompt: str | None
    ) -> str:
        payload = await self._call_groq_api(chunk.data, lang, prompt)
        if payload is None:
            return TRANSCRIPTION_ERROR
        return filter_transcription(payload, chunk.activity)

    def _prepare_audio_chunks(self, file_path: str, mime_type: str) -> list[AudioChunk]:
        fmt = self._mime_to_format(mime_type)
        audio = AudioSegment.from_file(file_path, format=fmt)
        chunks = _split_audio(audio)
        if len(chunks) > 1:
            logger.info("Transcribing %.1fs audio in %d chunks", len(audio) / 1000, len(chunks))
        encoded = []
        for chunk in chunks:
            # Skip exact digital silence; an amplitude threshold could drop
            # quiet speech. Other non-speech audio is checked by Silero below.
            if chunk.max == 0:
                continue
            activity = self._speech_detector.analyze(chunk)
            if not activity.has_possible_speech:
                logger.info(
                    "Skipped %.2fs chunk without speech (vad=%.3f speech_duration=%.3f)",
                    len(chunk) / 1000, activity.probability(), activity.speech_duration(),
                )
                continue
            buf = io.BytesIO()
            chunk.export(buf, format="mp3", bitrate="64k")
            encoded.append(AudioChunk(buf.getvalue(), activity))
        return encoded

    async def _call_groq_api(
        self, audio_bytes: bytes, lang: str, prompt: str | None
    ) -> dict | None:
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
                data.add_field("response_format", "verbose_json")
                data.add_field("timestamp_granularities[]", "segment")
                if prompt:
                    data.add_field("prompt", prompt)

                async with session.post(
                    GROQ_TRANSCRIPTION_URL, headers=headers, data=data
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()

                    body = await resp.text()
                    retryable = resp.status == 429 or 500 <= resp.status < 600
                    if not retryable or attempt == MAX_API_ATTEMPTS - 1:
                        logger.error("Groq API error %s: %s", resp.status, body)
                        return None

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

        return None

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
