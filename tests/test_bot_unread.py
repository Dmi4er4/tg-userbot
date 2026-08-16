import unittest
import sys
from datetime import datetime, timezone
from types import ModuleType
from unittest.mock import Mock

if "yandex_music" not in sys.modules:
    yandex_music = ModuleType("yandex_music")
    yandex_music.ClientAsync = object
    sys.modules["yandex_music"] = yandex_music

from telethon.tl import types
from telethon.tl.functions.messages import MarkDialogUnreadRequest

from src_py.presentation.bot import TgUserbot
from src_py.presentation.handlers import create_handlers


class RecordingClient:
    def __init__(self) -> None:
        self.requests: list[object] = []

    async def __call__(self, request: object) -> object:
        self.requests.append(request)
        return object()


class BotUnreadPreservationTest(unittest.IsolatedAsyncioTestCase):
    async def test_auto_transcribe_marks_dialog_and_preserves_tracker_state(self) -> None:
        client = RecordingClient()
        bot = TgUserbot(client, [], channel_id=-100123)
        bot._deleted_tracker = Mock()
        message = types.Message(
            id=17,
            peer_id=types.PeerUser(42),
            from_id=types.PeerUser(42),
            date=datetime.now(timezone.utc),
            message="video note",
        )

        await bot._preserve_dialog_unread(message)

        self.assertEqual(len(client.requests), 1)
        self.assertIsInstance(client.requests[0], MarkDialogUnreadRequest)
        self.assertTrue(client.requests[0].unread)
        bot._deleted_tracker.preserve_unread.assert_called_once_with(message)

    async def test_auto_transcribe_handler_opts_into_unread_preservation(self) -> None:
        handlers = create_handlers(
            transcriber=Mock(),
            channel_id=-100123,
            auto_transcribe_peer_ids=set(),
            transcribe_disabled_peer_ids=set(),
        )

        auto_transcribe = next(
            handler
            for handler in handlers
            if handler.name == "Private auto voice/videonote"
        )

        self.assertTrue(auto_transcribe.preserve_unread)


if __name__ == "__main__":
    unittest.main()
