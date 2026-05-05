import asyncio
import logging
import time
from datetime import datetime, timezone

from telethon import TelegramClient, events
from telethon.tl import types

from src_py.application.diary.pings import build_ping_table

logger = logging.getLogger(__name__)


def _extract_channel_raw_id(configured: int | None) -> int | None:
    if configured is None:
        return None
    raw = abs(configured)
    s = str(raw)
    if s.startswith("100") and len(s) > 3:
        return int(s[3:])
    return raw


class DeadHand:
    def __init__(
        self,
        *,
        duration_seconds: int,
        userbot_channel: object,
        userbot_channel_id: int | None,
        taak_peer: object,
        self_user_id: int,
    ) -> None:
        self._duration = duration_seconds
        self._userbot_channel = userbot_channel
        self._userbot_channel_raw = _extract_channel_raw_id(userbot_channel_id)
        self._taak_peer = taak_peer
        self._self_user_id = self_user_id

        self._client: TelegramClient | None = None
        self._deadline: float = 0.0
        self._released = False
        self._last_ping_key: str | None = None
        self._wakeup = asyncio.Event()
        self._scheduler_task: asyncio.Task | None = None
        self._ping_table = build_ping_table()

    @property
    def deadline(self) -> float:
        return self._deadline

    def is_released(self) -> bool:
        return self._released

    async def start(self, client: TelegramClient) -> None:
        self._client = client
        self._deadline = time.time() + self._duration
        self._last_ping_key = None
        self._wakeup.clear()
        client.add_event_handler(self._on_outgoing, events.NewMessage(outgoing=True))
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        logger.info(
            "[DeadHand] started; deadline=%s",
            datetime.fromtimestamp(self._deadline, tz=timezone.utc).isoformat(),
        )

    async def stop(self) -> None:
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except (asyncio.CancelledError, Exception):
                pass
            self._scheduler_task = None

    def reset(self) -> None:
        if self._released:
            return
        self._deadline = time.time() + self._duration
        self._last_ping_key = None
        self._wakeup.set()
        logger.info(
            "[DeadHand] reset; deadline=%s",
            datetime.fromtimestamp(self._deadline, tz=timezone.utc).isoformat(),
        )

    def _is_userbot_channel_peer(self, peer: object) -> bool:
        if isinstance(peer, types.PeerChannel):
            if self._userbot_channel_raw is not None:
                return peer.channel_id == self._userbot_channel_raw
            return False
        if isinstance(peer, types.PeerUser):
            if self._userbot_channel_raw is None:
                return peer.user_id == self._self_user_id
        return False

    async def _on_outgoing(self, event: events.NewMessage.Event) -> None:
        try:
            if self._released:
                return
            msg = event.message
            if not isinstance(msg, types.Message):
                return
            if self._is_userbot_channel_peer(msg.peer_id):
                return
            self.reset()
        except Exception:
            logger.exception("[DeadHand] activity tracker error")

    async def _scheduler_loop(self) -> None:
        try:
            while True:
                if self._released:
                    return
                now = time.time()
                remaining = self._deadline - now
                if remaining <= 0:
                    await self._fire_release()
                    return

                await self._fire_due_pings(remaining)

                sleep_target = self._deadline
                found_last = self._last_ping_key is None
                for thresh, key, _msg_fn in self._ping_table:
                    if not found_last:
                        if key == self._last_ping_key:
                            found_last = True
                        continue
                    fire_time = self._deadline - thresh
                    if fire_time > now:
                        sleep_target = min(sleep_target, fire_time)
                    break

                sleep_s = max(0.5, sleep_target - now)
                try:
                    await asyncio.wait_for(self._wakeup.wait(), timeout=sleep_s)
                    self._wakeup.clear()
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[DeadHand] scheduler loop crashed")

    async def _fire_due_pings(self, remaining: float) -> None:
        if self._client is None:
            return
        passed_last = self._last_ping_key is None
        for thresh, key, msg_fn in self._ping_table:
            if not passed_last:
                if key == self._last_ping_key:
                    passed_last = True
                continue
            if remaining > thresh:
                continue
            try:
                await self._client.send_message(
                    self._userbot_channel, msg_fn(remaining)
                )
            except Exception:
                logger.exception("[DeadHand] ping send failed (key=%s)", key)
            self._last_ping_key = key

    async def _fire_release(self) -> None:
        if self._client is None:
            return
        logger.warning("[DeadHand] FIRING release")
        started_at = self._deadline - self._duration
        started_iso = datetime.fromtimestamp(started_at, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"
        )
        try:
            await self._client.send_message(
                self._taak_peer,
                f"Dead-hand triggered. Owner inactive since {started_iso}. Diary entries follow.",
            )
        except Exception:
            logger.exception("[DeadHand] summary send failed")

        try:
            ids: list[int] = []
            async for msg in self._client.iter_messages(self._userbot_channel):
                if not isinstance(msg, types.Message):
                    continue
                text = msg.message or ""
                if text.lstrip().startswith("#diary"):
                    ids.append(msg.id)
            ids.reverse()  # chronological (iter_messages yields newest-first)

            for i in range(0, len(ids), 100):
                batch = ids[i : i + 100]
                try:
                    await self._client.forward_messages(
                        self._taak_peer, batch, self._userbot_channel
                    )
                except Exception:
                    logger.exception("[DeadHand] forward batch failed")
            logger.warning("[DeadHand] release: forwarded %d entries", len(ids))
        except Exception:
            logger.exception("[DeadHand] release scan failed")

        self._released = True
