import unittest
from unittest.mock import AsyncMock, Mock, patch

from telethon.tl import types

from src_py.application.use_cases.private_transcribe import private_transcribe_voice


class PrivateTranscribeOutcomeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.client = Mock()
        self.message = types.Message(id=17, peer_id=types.PeerUser(42))

    async def test_empty_result_is_not_a_transcription(self) -> None:
        with (
            patch(
                "src_py.application.use_cases.private_transcribe.is_voice_message",
                return_value=True,
            ),
            patch(
                "src_py.application.use_cases.private_transcribe.transcribe_voice_message",
                new_callable=AsyncMock,
                return_value="  ",
            ),
            patch(
                "src_py.application.use_cases.private_transcribe.send_transcription_reply",
                new_callable=AsyncMock,
            ) as send_reply,
        ):
            result = await private_transcribe_voice(
                self.client, self.message, transcriber=Mock()
            )

        self.assertIs(result, False)
        send_reply.assert_not_awaited()

    async def test_service_error_is_not_a_transcription(self) -> None:
        for error_text in (
            "(ошибка транскрибации)",
            "(не удалось распознать речь)",
        ):
            with self.subTest(error_text=error_text):
                with (
                    patch(
                        "src_py.application.use_cases.private_transcribe.is_voice_message",
                        return_value=True,
                    ),
                    patch(
                        "src_py.application.use_cases.private_transcribe.transcribe_voice_message",
                        new_callable=AsyncMock,
                        return_value=error_text,
                    ),
                    patch(
                        "src_py.application.use_cases.private_transcribe.send_transcription_reply",
                        new_callable=AsyncMock,
                    ) as send_reply,
                ):
                    result = await private_transcribe_voice(
                        self.client, self.message, transcriber=Mock()
                    )

                self.assertIs(result, False)
                send_reply.assert_awaited_once()

    async def test_sent_transcript_reports_success(self) -> None:
        with (
            patch(
                "src_py.application.use_cases.private_transcribe.is_voice_message",
                return_value=True,
            ),
            patch(
                "src_py.application.use_cases.private_transcribe.transcribe_voice_message",
                new_callable=AsyncMock,
                return_value="Распознанный текст",
            ),
            patch(
                "src_py.application.use_cases.private_transcribe.build_summary",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "src_py.application.use_cases.private_transcribe.send_transcription_reply",
                new_callable=AsyncMock,
            ) as send_reply,
        ):
            result = await private_transcribe_voice(
                self.client, self.message, transcriber=Mock()
            )

        self.assertTrue(result)
        send_reply.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
