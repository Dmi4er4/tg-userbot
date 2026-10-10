import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from pydub import AudioSegment
from telethon.tl import types

from src_py.application.use_cases.private_transcribe import private_transcribe_voice
from src_py.impl.speech_activity import SpeechActivity
from benchmarks.legacy_filter import _strip_hallucinations
from src_py.impl.groq_whisper_transcriber import (
    GroqWhisperTranscriber,
    _split_audio,
    AudioChunk,
)


def payload(text, *, no_speech=0.01, logprob=-0.2):
    return {"text": text, "segments": [{"text": text, "start": 0, "end": 1,
            "no_speech_prob": no_speech, "avg_logprob": logprob}]}


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
        return str(self.body)

    async def json(self) -> dict:
        return self.body if isinstance(self.body, dict) else payload(self.body)


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


class HallucinationFilterTest(unittest.TestCase):
    def test_subtitle_credits_are_empty(self) -> None:
        for text in (
            "Субтитры добавил DimaTorzok",
            "Субтитры подогнал «Симон»!",
            "Редактор субтитров М.Лосева Корректор А.Егорова",
            "Редактор субтитров А. Синецкая. Корректор А. Егорова.",
            "Subtitles by the Amara.org community.",
            "Subtitles created by Amara.org",
        ):
            with self.subTest(text=text):
                self.assertEqual(_strip_hallucinations(text), "")

    def test_outros_and_repeated_phrases_are_empty(self) -> None:
        for text in (
            "Спасибо за просмотр!!!",
            "Спасибо за прослушивание.",
            "Подписывайтесь на наш канал!",
            "Подпишись на мой канал! Ставьте лайки!",
            "«Продолжение следует…»",
            "Смотрите продолжение во второй части видео.",
            "Смотрите продолжение в следующей серии...",
            "Смотрите продолжение в 4 части видео.",
            "Thank you for watching! Thanks for watching...",
            "[Музыка] Спасибо за внимание...\n(тишина)",
        ):
            with self.subTest(text=text):
                self.assertEqual(_strip_hallucinations(text), "")

    def test_non_speech_labels_are_empty(self) -> None:
        for text in (
            "[музыка]",
            "(МУЗЫКА)",
            "НАПРЯЖЕННАЯ МУЗЫКА",
            "НАПРЯЖЁННАЯ МУЗЫКА",
            "Грустная мелодия.",
            "МУЗЫКАЛЬНАЯ ЗАСТАВКА",
            "[шум дождя]",
            "Городской шум",
            "РЁВ МОТОРА",
            "Лай собаки",
            "(аплодисменты) [смех]",
            "Тишина.\nПауза. Нет звука.",
            "[неразборчиво]",
            "[BLANK_AUDIO]",
            "[silence] (music) [inaudible]",
            "[no speech] [no audio]",
        ):
            with self.subTest(text=text):
                self.assertEqual(_strip_hallucinations(text), "")

    def test_punctuation_and_symbols_alone_are_empty(self) -> None:
        for text in ("", " \n", "...", "…", "[] ()", "♪ ♫", "---", "___"):
            with self.subTest(text=text):
                self.assertEqual(_strip_hallucinations(text), "")

    def test_real_speech_is_preserved(self) -> None:
        for text in (
            "Мне нужна музыка для видео.",
            "Смехотворная идея, но давай попробуем.",
            "На записи слышен шум дождя и лай собаки.",
            "В комнате нет звука, проверь микрофон.",
            "Музыка. Встречаемся завтра в пять.",
            "Подпишитесь на канализацию в новом доме.",
            "Подпишитесь на обновления проекта.",
            "Да.",
            "Спасибо!",
            "Поехали!",
            "42",
            "(ошибка транскрибации)",
        ):
            with self.subTest(text=text):
                self.assertEqual(_strip_hallucinations(text), text)

    def test_credits_do_not_consume_following_speech(self) -> None:
        for text in (
            "Редактор субтитров М.Лосева. Встречаемся завтра.",
            "Subtitles by Amara.org. Встречаемся завтра.",
            "Ставьте лайки! Встречаемся завтра.",
        ):
            with self.subTest(text=text):
                self.assertEqual(_strip_hallucinations(text), "Встречаемся завтра.")


class SilentAudioTest(unittest.IsolatedAsyncioTestCase):
    async def test_digital_silence_never_reaches_api(self) -> None:
        for duration in (0, 5_000, 125_000):
            with self.subTest(duration=duration):
                transcriber = GroqWhisperTranscriber("unused-key")
                transcriber._call_groq_api = AsyncMock()
                with (
                    patch(
                        "src_py.impl.groq_whisper_transcriber.AudioSegment.from_file",
                        return_value=AudioSegment.silent(duration=duration),
                    ),
                    patch.object(AudioSegment, "export") as export,
                ):
                    result = await transcriber.transcribe_file("unused.ogg", "audio/ogg")

                self.assertEqual(result, "")
                transcriber._call_groq_api.assert_not_awaited()
                export.assert_not_called()

    async def test_even_quiet_nonzero_audio_reaches_api(self) -> None:
        # RMS rounds to zero here, but the samples are not all zero.
        audio = AudioSegment(
            data=b"\x01\x00\x00\x00" * 8_000,
            sample_width=2,
            frame_rate=16_000,
            channels=1,
        )
        transcriber = GroqWhisperTranscriber("unused-key")
        transcriber._speech_detector.analyze = Mock(return_value=SpeechActivity(1, (0.9,) * 32))
        transcriber._call_groq_api = AsyncMock(return_value=payload("Тихая речь"))

        def export_audio(_chunk, buffer, **_kwargs):
            buffer.write(b"encoded-audio")

        with (
            patch(
                "src_py.impl.groq_whisper_transcriber.AudioSegment.from_file",
                return_value=audio,
            ),
            patch.object(AudioSegment, "export", new=export_audio),
        ):
            result = await transcriber.transcribe_file("unused.ogg", "audio/ogg")

        self.assertEqual(result, "Тихая речь")
        transcriber._call_groq_api.assert_awaited_once_with(b"encoded-audio", "ru", None)


class AutoTranscriptionFilterTest(unittest.IsolatedAsyncioTestCase):
    async def test_empty_api_transcripts_do_not_send_replies(self) -> None:
        for text in (
            "Субтитры добавил DimaTorzok",
            "Редактор субтитров М.Лосева Корректор А.Егорова",
            "[музыка] Спасибо за просмотр!!!",
            "...",
        ):
            with self.subTest(text=text):
                transcriber = GroqWhisperTranscriber("unused-key")
                transcriber._prepare_audio_chunks = Mock(return_value=[AudioChunk(b"audio", SpeechActivity(1, (0.2,) * 32))])
                session = FakeSession([FakeResponse(200, payload(text, no_speech=0.9, logprob=-2.0))])
                with (
                    patch(
                        "src_py.application.use_cases.private_transcribe.is_voice_message",
                        return_value=True,
                    ),
                    patch(
                        "src_py.application.use_cases.transcription.save_voice_from_message",
                        new_callable=AsyncMock,
                        return_value="unused.ogg",
                    ),
                    patch(
                        "src_py.impl.groq_whisper_transcriber.aiohttp.ClientSession",
                        return_value=session,
                    ),
                    patch(
                        "src_py.application.use_cases.private_transcribe.send_transcription_reply",
                        new_callable=AsyncMock,
                    ) as send_reply,
                ):
                    result = await private_transcribe_voice(
                        Mock(),
                        types.Message(id=17, peer_id=types.PeerUser(42)),
                        transcriber=transcriber,
                    )

                self.assertIs(result, False)
                send_reply.assert_not_awaited()


class AudioChunkingTest(unittest.TestCase):
    def test_short_audio_remains_one_piece(self) -> None:
        audio = AudioSegment.silent(duration=60_000, frame_rate=16_000)

        self.assertEqual(_split_audio(audio), [audio])

    def test_long_audio_has_balanced_contiguous_chunks(self) -> None:
        audio = AudioSegment.silent(duration=227_500, frame_rate=16_000)

        chunks = _split_audio(audio)

        self.assertEqual(len(chunks), 4)
        self.assertEqual(sum(map(len, chunks)), len(audio))
        self.assertTrue(all(45_000 <= len(chunk) <= 70_000 for chunk in chunks))

    def test_without_detectable_pause_still_covers_entire_audio(self) -> None:
        audio = AudioSegment.silent(duration=115_000, frame_rate=16_000)

        with patch("src_py.impl.groq_whisper_transcriber.detect_silence", return_value=[]):
            chunks = _split_audio(audio)

        self.assertEqual(len(chunks), 2)
        self.assertEqual(sum(map(len, chunks)), len(audio))
        self.assertTrue(all(len(chunk) >= 45_000 for chunk in chunks))


class ParallelTranscriptionTest(unittest.IsolatedAsyncioTestCase):
    async def test_boilerplate_split_between_audio_chunks_is_suppressed(self) -> None:
        transcriber = GroqWhisperTranscriber("unused-key")
        transcriber._prepare_audio_chunks = Mock(return_value=[b"first", b"second"])
        transcriber._transcribe_chunk = AsyncMock(side_effect=["Да. Продолжение", "следует..."])

        result = await transcriber.transcribe_file("unused.ogg", "audio/ogg")

        self.assertEqual(result, "Да.")

    async def test_parallel_calls_keep_original_chunk_order(self) -> None:
        transcriber = GroqWhisperTranscriber("unused-key")
        transcriber._prepare_audio_chunks = Mock(return_value=[b"first", b"second", b"third"])

        async def transcribe(data: bytes, _lang: str, _prompt: str | None) -> str:
            await asyncio.sleep({b"first": 0.03, b"second": 0.02, b"third": 0.01}[data])
            return data.decode()

        transcriber._transcribe_chunk = AsyncMock(side_effect=transcribe)

        result = await transcriber.transcribe_file("unused.ogg", "audio/ogg")

        self.assertEqual(result, "first second third")
        self.assertEqual(transcriber._transcribe_chunk.await_count, 3)

    async def test_failed_chunk_does_not_return_partial_transcript(self) -> None:
        transcriber = GroqWhisperTranscriber("unused-key")
        transcriber._prepare_audio_chunks = Mock(return_value=[b"first", b"second"])
        transcriber._transcribe_chunk = AsyncMock(
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

        self.assertEqual(result["text"], "Распознанный текст")
        self.assertEqual(session.post_count, 2)
        sleep.assert_awaited_once_with(2.0)


if __name__ == "__main__":
    unittest.main()
