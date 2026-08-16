import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from telethon.tl import types

from src_py.telegram_utils.deleted_message_tracker import (
    CachedMessage,
    DeletedMessageTracker,
)


class DeletedMessageTrackerUnreadOverrideTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.peer = types.PeerUser(42)
        self.message = types.Message(
            id=17,
            peer_id=self.peer,
            from_id=self.peer,
            date=datetime.now(timezone.utc),
            message="video note",
            media_unread=True,
        )
        self.tracker = DeletedMessageTracker(
            client=object(),
            self_user_id="1",
            channel_id=-100123,
        )
        self.cached = CachedMessage(
            message_id=self.message.id,
            text=self.message.message,
            date=self.message.date,
            cached_at=0,
            sender_id="42",
            sender_name="Sender",
            peer=self.peer,
            chat_label="user-42",
            media_description="Video note",
            media=None,
            channel_id=None,
        )
        self.tracker._cache["msg:17"] = self.cached

    async def test_auto_transcribed_message_stays_logically_unread(self) -> None:
        self.tracker._handle_read_inbox(
            types.UpdateReadHistoryInbox(
                peer=self.peer,
                max_id=self.message.id,
                still_unread_count=0,
                pts=1,
                pts_count=1,
            )
        )
        self.assertFalse(self.tracker._is_unread(self.cached))

        self.tracker.preserve_unread(self.message)

        self.assertTrue(self.tracker._is_unread(self.cached))
        self.tracker._send_to_saved = AsyncMock()
        await self.tracker._handle_delete_messages(
            types.UpdateDeleteMessages(
                messages=[self.message.id],
                pts=2,
                pts_count=1,
            )
        )
        self.tracker._send_to_saved.assert_awaited_once()

    async def test_opening_marked_dialog_clears_logical_unread_override(self) -> None:
        self.tracker._handle_read_inbox(
            types.UpdateReadHistoryInbox(
                peer=self.peer,
                max_id=self.message.id,
                still_unread_count=0,
                pts=1,
                pts_count=1,
            )
        )
        self.tracker.preserve_unread(self.message)

        await self.tracker._on_raw_update(
            types.UpdateDialogUnreadMark(
                peer=types.DialogPeer(self.peer),
                unread=False,
            )
        )

        self.assertFalse(self.tracker._is_unread(self.cached))
        self.tracker._send_to_saved = AsyncMock()
        await self.tracker._handle_delete_messages(
            types.UpdateDeleteMessages(
                messages=[self.message.id],
                pts=2,
                pts_count=1,
            )
        )
        self.tracker._send_to_saved.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
