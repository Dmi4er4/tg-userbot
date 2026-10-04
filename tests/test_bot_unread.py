import unittest
import sys
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

if "yandex_music" not in sys.modules:
    yandex_music = ModuleType("yandex_music")
    yandex_music.ClientAsync = object
    sys.modules["yandex_music"] = yandex_music

from telethon.tl import types
from telethon.tl.functions.messages import MarkDialogUnreadRequest

from src_py.presentation.bot import TgUserbot
from src_py.presentation.handlers import Handler, create_handlers


class RecordingClient:
    def __init__(self) -> None:
        self.requests: list[object] = []
        self.latest_message: types.Message | None = None
        self.get_messages_calls: list[object] = []

    async def __call__(self, request: object) -> object:
        self.requests.append(request)
        return object()

    async def get_messages(self, peer: object, *, limit: int) -> list[types.Message]:
        self.get_messages_calls.append((peer, limit))
        return [self.latest_message] if self.latest_message else []


class BotUnreadPreservationTest(unittest.IsolatedAsyncioTestCase):
    async def _dispatch_auto_transcription(
        self, *, outgoing: bool, transcribed: bool, latest_outgoing: bool = True
    ) -> tuple[RecordingClient, Mock]:
        client = RecordingClient()
        handler = Handler(
            name="Private auto voice/videonote",
            is_triggered=AsyncMock(return_value=True),
            handle=AsyncMock(return_value=transcribed),
            preserve_unread=True,
        )
        bot = TgUserbot(client, [handler], channel_id=-100123)
        bot._self_user_id = "1"
        tracker = Mock()
        tracker.cache_message = AsyncMock()
        bot._deleted_tracker = tracker
        message = types.Message(
            id=17,
            peer_id=types.PeerUser(42),
            from_id=types.PeerUser(1 if outgoing else 42),
            out=outgoing,
            date=datetime.now(timezone.utc),
        )
        client.latest_message = types.Message(
            id=18,
            peer_id=message.peer_id,
            from_id=types.PeerUser(1 if latest_outgoing else 42),
            out=latest_outgoing,
            date=datetime.now(timezone.utc),
        )

        await bot._on_new_message(SimpleNamespace(message=message))

        handler.handle.assert_awaited_once_with(client, message)
        return client, tracker

    async def test_outgoing_note_does_not_mark_own_dialog_unread(self) -> None:
        for transcribed in (True, False):
            with self.subTest(transcribed=transcribed):
                client, tracker = await self._dispatch_auto_transcription(
                    outgoing=True, transcribed=transcribed
                )

                self.assertEqual(client.requests, [])
                self.assertEqual(client.get_messages_calls, [])
                tracker.preserve_unread.assert_not_called()

    async def test_empty_transcription_does_not_mark_dialog_unread(self) -> None:
        client, tracker = await self._dispatch_auto_transcription(
            outgoing=False, transcribed=False
        )

        self.assertEqual(client.requests, [])
        tracker.preserve_unread.assert_not_called()

    async def test_successful_incoming_transcription_with_own_last_message_has_no_badge(self) -> None:
        client, tracker = await self._dispatch_auto_transcription(
            outgoing=False, transcribed=True
        )

        self.assertEqual(client.requests, [])
        self.assertEqual(len(client.get_messages_calls), 1)
        tracker.preserve_unread.assert_called_once()

    async def test_new_incoming_last_message_can_keep_unread_badge(self) -> None:
        client, tracker = await self._dispatch_auto_transcription(
            outgoing=False, transcribed=True, latest_outgoing=False
        )

        self.assertEqual(len(client.requests), 1)
        self.assertIsInstance(client.requests[0], MarkDialogUnreadRequest)
        tracker.preserve_unread.assert_called_once()

    async def test_unknown_last_message_does_not_add_unread_badge(self) -> None:
        client = RecordingClient()
        bot = TgUserbot(client, [], channel_id=-100123)
        bot._self_user_id = "1"
        bot._deleted_tracker = Mock()
        message = types.Message(
            id=17,
            peer_id=types.PeerUser(42),
            from_id=types.PeerUser(42),
            out=False,
        )

        await bot._preserve_dialog_unread(message)

        self.assertEqual(client.requests, [])
        bot._deleted_tracker.preserve_unread.assert_called_once_with(message)

    async def test_auto_transcribe_marks_dialog_and_preserves_tracker_state(self) -> None:
        client = RecordingClient()
        bot = TgUserbot(client, [], channel_id=-100123)
        bot._deleted_tracker = Mock()
        message = types.Message(
            id=17,
            peer_id=types.PeerUser(42),
            from_id=types.PeerUser(42),
            out=False,
            date=datetime.now(timezone.utc),
            message="video note",
        )
        client.latest_message = types.Message(
            id=18,
            peer_id=message.peer_id,
            from_id=types.PeerUser(42),
            out=False,
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
