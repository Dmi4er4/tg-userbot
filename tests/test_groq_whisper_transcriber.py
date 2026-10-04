import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from pydub import AudioSegment

from src_py.impl.groq_whisper_transcriber import (
    GroqWhisperTranscriber,
    _split_audio,
)


class FakeResponse:
    def __init__(self, status: int, body: str, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self.body = body
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def text(self) -> str:
        return self.body


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = iter(responses)
        self.post_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def post(self, *_args, **_kwargs) -> FakeResponse:
        self.post_count += 1
        return next(self.responses)


class AudioChunkingTest(unittest.TestCase):
    def test_short_audio_remains_one_piece(self) -> None:
        audio = AudioSegment.silent(duration=60_000, frame_rate=16_000)

        self.assertEqual(_split_audio(audio), [audio])

    def test_long_audio_has_balanced_contiguous_chunks(self) -> None:
        audio = AudioSegment.silent(duration=227_500, frame_rate=16_000)

        chunks = _split_audio(audio)

        self.assertEqual(len(chunks), 3)
        self.assertEqual(sum(map(len, chunks)), len(audio))
        self.assertTrue(all(65_000 <= len(chunk) <= 90_000 for chunk in chunks))

    def test_without_detectable_pause_still_covers_entire_audio(self) -> None:
        audio = AudioSegment.silent(duration=115_000, frame_rate=16_000)

        with patch("src_py.impl.groq_whisper_transcriber.detect_silence", return_value=[]):
            chunks = _split_audio(audio)

        self.assertEqual(len(chunks), 2)
        self.assertEqual(sum(map(len, chunks)), len(audio))
        self.assertTrue(all(len(chunk) >= 45_000 for chunk in chunks))


class ParallelTranscriptionTest(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_calls_keep_original_chunk_order(self) -> None:
        transcriber = GroqWhisperTranscriber("unused-key")
        transcriber._prepare_audio_chunks = Mock(return_value=[b"first", b"second", b"third"])

        async def transcribe(data: bytes, _lang: str, _prompt: str | None) -> str:
            await asyncio.sleep({b"first": 0.03, b"second": 0.02, b"third": 0.01}[data])
            return data.decode()

        transcriber._call_groq_api = AsyncMock(side_effect=transcribe)

        result = await transcriber.transcribe_file("unused.ogg", "audio/ogg")

        self.assertEqual(result, "first second third")
        self.assertEqual(transcriber._call_groq_api.await_count, 3)

    async def test_failed_chunk_does_not_return_partial_transcript(self) -> None:
        transcriber = GroqWhisperTranscriber("unused-key")
        transcriber._prepare_audio_chunks = Mock(return_value=[b"first", b"second"])
        transcriber._call_groq_api = AsyncMock(
            side_effect=["first part", "(ошибка транскрибации)"]
        )

        result = await transcriber.transcribe_file("unused.mp4", "video/mp4")

        self.assertEqual(result, "(ошибка транскрибации)")

    async def test_rate_limit_retries_with_fresh_request(self) -> None:
        transcriber = GroqWhisperTranscriber("unused-key")
        session = FakeSession(
            [
                FakeResponse(429, "rate limit", {"Retry-After": "2"}),
                FakeResponse(200, "Распознанный текст"),
            ]
        )

        with (
            patch(
                "src_py.impl.groq_whisper_transcriber.aiohttp.ClientSession",
                return_value=session,
            ),
            patch(
                "src_py.impl.groq_whisper_transcriber.asyncio.sleep",
                new_callable=AsyncMock,
            ) as sleep,
        ):
            result = await transcriber._call_groq_api(b"audio", "ru", None)

        self.assertEqual(result, "Распознанный текст")
        self.assertEqual(session.post_count, 2)
        sleep.assert_awaited_once_with(2.0)


if __name__ == "__main__":
    unittest.main()
