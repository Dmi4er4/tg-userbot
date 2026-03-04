import logging

from telethon import TelegramClient, events
from telethon.tl import types
from telethon.tl.functions.messages import UpdatePinnedMessageRequest
from telethon.tl.types import InputMessagesFilterPinned

from src_py.presentation.handlers import Handler
from src_py.telegram_utils.deleted_message_tracker import DeletedMessageTracker

logger = logging.getLogger(__name__)

HELP_TEXT = """**📋 Userbot — команды и возможности**

**Команды** (отправляй в любой чат):
`.convert` — транскрибация голосового/видеокружка (ответом на сообщение)
`.save [#тег]` — сохранить сообщение в канал юзербота (по умолчанию #save)
`.id` — получить ID пользователя (ответом) или чата
`.sticker` — конвертировать стикер в фото (ответом на стикер)
`.ss <url>` — скриншот сайта
`.w <запрос>` — поиск в Википедии (сначала RU, потом EN)
`.g <запрос>` — ссылка на поиск Google
`.n <текст>` — добавить дисклеймер GTA 5 RP
`.ai <вопрос>` — задать вопрос AI (Gemini), можно ответом на сообщение
`.ym <ссылка>` — скачать трек из Яндекс Музыки в MP3
`.r <время> [текст]` — напоминание через ntfy (15m, 2h, 14:00, 2026-03-05 14:00)

**Автоматические функции:**
• Транскрибация голосовых в личных сообщениях
• Транскрибация в выбранных группах (AUTO\\_TRANSCRIBE\\_PEER\\_IDS)
• Сохранение исчезающих медиа (#disappearing)
• Трекинг удалённых/отредактированных сообщений (#deleted / #edited)"""


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

        await self._pin_help_message()

        self._client.add_event_handler(self._on_new_message, events.NewMessage)

    async def _pin_help_message(self) -> None:
        if self._channel_id == "me":
            return
        try:
            await self._delete_old_help_messages()
            msg = await self._client.send_message(self._channel_id, HELP_TEXT)
            await self._client(
                UpdatePinnedMessageRequest(
                    peer=self._channel_id,
                    id=msg.id,
                    silent=True,
                )
            )
            logger.info("Help message pinned (msg_id=%s)", msg.id)
        except Exception:
            logger.exception("Failed to pin help message")

    async def _delete_old_help_messages(self) -> None:
        try:
            ids_to_delete = []
            pinned_msg_ids = set()
            async for msg in self._client.iter_messages(
                self._channel_id,
                filter=InputMessagesFilterPinned,
            ):
                if (
                    isinstance(msg, types.Message)
                    and msg.message
                    and msg.message.startswith("\U0001f4cb Userbot")
                ):
                    ids_to_delete.append(msg.id)
                    pinned_msg_ids.add(msg.id)
            # Also find "pinned a message" service messages for these pins
            if pinned_msg_ids:
                async for msg in self._client.iter_messages(
                    self._channel_id, limit=50
                ):
                    if (
                        isinstance(msg, types.MessageService)
                        and isinstance(msg.action, types.MessageActionPinMessage)
                        and msg.reply_to
                        and getattr(msg.reply_to, "reply_to_msg_id", None)
                        in pinned_msg_ids
                    ):
                        ids_to_delete.append(msg.id)
            if ids_to_delete:
                await self._client.delete_messages(
                    self._channel_id, ids_to_delete
                )
                logger.info("Deleted %d old help/pin messages", len(ids_to_delete))
        except Exception:
            logger.exception("Failed to delete old help messages")

    async def _on_new_message(self, event: events.NewMessage.Event) -> None:
        message = event.message
        if not isinstance(message, types.Message):
            return

        if self._deleted_tracker:
            try:
                await self._deleted_tracker.cache_message(message)
            except Exception:
                logger.exception("[DeletedMessageTracker] cache error")

        sender_id = str(message.from_id.user_id) if isinstance(message.from_id, types.PeerUser) else None
        text = (message.message or "")[:50]
        logger.debug(
            "[bot] msg from=%s self=%s text=%r",
            sender_id, self._self_user_id, text,
        )

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
