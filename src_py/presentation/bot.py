import logging

from telethon import TelegramClient, events
from telethon.tl import types

from src_py.presentation.handlers import Handler
from src_py.telegram_utils.deleted_message_tracker import DeletedMessageTracker

logger = logging.getLogger(__name__)


class TgUserbot:
    def __init__(
        self,
        client: TelegramClient,
        handlers: list[Handler],
        *,
        deleted_tracker_enabled: bool = True,
        channel_id: object,
    ) -> None:
        self._client = client
        self._handlers = handlers
        self._deleted_tracker_enabled = deleted_tracker_enabled
        self._channel_id = channel_id
        self._self_user_id: str | None = None
        self._deleted_tracker: DeletedMessageTracker | None = None

    async def start(self) -> None:
        me = await self._client.get_me()
        if isinstance(me, types.User):
            self._self_user_id = str(me.id)

        if self._deleted_tracker_enabled and isinstance(me, types.User):
            self._deleted_tracker = DeletedMessageTracker(
                self._client, str(me.id), self._channel_id
            )
            self._deleted_tracker.start()

        self._client.add_event_handler(self._on_new_message, events.NewMessage)

    async def _on_new_message(self, event: events.NewMessage.Event) -> None:
        message = event.message
        if not isinstance(message, types.Message):
            return

        if self._deleted_tracker:
            try:
                await self._deleted_tracker.cache_message(message)
            except Exception:
                logger.exception("[DeletedMessageTracker] cache error")

        for h in self._handlers:
            try:
                triggered = await h.is_triggered(
                    self._client, message, self._self_user_id
                )
                if triggered:
                    logger.info("[handler:%s] started", h.name)
                    await h.handle(self._client, message)
                    logger.info("[handler:%s] finished", h.name)
                    break
            except Exception:
                logger.exception("[handler:%s] errored", h.name)
