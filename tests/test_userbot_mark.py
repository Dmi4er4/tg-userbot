import os
import subprocess
import sys
import unittest
from unittest.mock import AsyncMock, patch

from telethon.tl import types

from src_py import messages
from src_py.telegram_utils.utils import send_formatted_reply, send_transcription_reply


class UserbotMarkTest(unittest.IsolatedAsyncioTestCase):
    async def test_outgoing_reply_uses_configured_mark(self) -> None:
        for mark in ("dmi4er4", "charndv", "taak"):
            with self.subTest(mark=mark), patch.object(messages, "USERBOT_MARK", mark):
                client = AsyncMock()

                await send_formatted_reply(client, 42, "Проверка")

                self.assertEqual(client.send_message.await_args.args[1], f"{mark}\nПроверка")

    async def test_summary_reply_uses_account_mark(self) -> None:
        message = types.Message(id=17, peer_id=types.PeerUser(42))
        for mark in ("dmi4er4", "charndv", "taak"):
            with self.subTest(mark=mark), patch.object(messages, "USERBOT_MARK", mark):
                client = AsyncMock()

                await send_transcription_reply(client, message, "Полный текст", "Кратко")

                self.assertTrue(
                    client.send_message.await_args.args[1].startswith(f"{mark}\nTL;DR:")
                )

    async def test_environment_selects_account_mark(self) -> None:
        for mark in ("dmi4er4", "charndv", "taak"):
            with self.subTest(mark=mark):
                env = {**os.environ, "USERBOT_MARK": mark}
                result = subprocess.run(
                    [sys.executable, "-c", "from src_py import messages; print(messages.USERBOT_MARK)"],
                    env=env,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                self.assertEqual(result.stdout.strip(), mark)


if __name__ == "__main__":
    unittest.main()
