import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo

from telethon import TelegramClient
from telethon.tl import types

from src_py.infrastructure.ntfy_client import send_ntfy
from src_py.infrastructure.reminder_store import ReminderStore
from src_py.telegram_utils.sender_name import get_sender_display_name
from src_py.telegram_utils.utils import get_replied_message, reply_to

logger = logging.getLogger(__name__)

_RELATIVE_RE = re.compile(r"^(\d+)\s*(s|m|h|d)$", re.IGNORECASE)
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_DATETIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})$")

_UNIT_MAP = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}


@dataclass
class NtfyConfig:
    url: str
    topic: str
    user: str
    password: str


@dataclass
class _ParsedTime:
    fire_at: datetime  # UTC
    human: str  # human-readable confirmation


def _parse_time(tokens: list[str], tz: tzinfo) -> tuple[_ParsedTime, int] | None:
    """Parse time from beginning of token list. Returns (parsed_time, tokens_consumed) or None."""
    if not tokens:
        return None

    # Relative: 15m, 2h, 1d, 30s
    match = _RELATIVE_RE.match(tokens[0])
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        delta = timedelta(**{_UNIT_MAP[unit]: amount})
        fire_at = datetime.now(timezone.utc) + delta
        return _ParsedTime(fire_at=fire_at, human=f"через {amount}{unit}"), 1

    # Absolute datetime: 2026-03-05 14:00
    if len(tokens) >= 2:
        combined = f"{tokens[0]} {tokens[1]}"
        match = _DATETIME_RE.match(combined)
        if match:
            dt = datetime.strptime(combined, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
            fire_at = dt.astimezone(timezone.utc)
            return _ParsedTime(fire_at=fire_at, human=combined), 2

    # Absolute time today: 14:00
    match = _TIME_RE.match(tokens[0])
    if match:
        now = datetime.now(tz)
        dt = now.replace(
            hour=int(match.group(1)),
            minute=int(match.group(2)),
            second=0,
            microsecond=0,
        )
        if dt <= now:
            dt += timedelta(days=1)
        fire_at = dt.astimezone(timezone.utc)
        return _ParsedTime(fire_at=fire_at, human=tokens[0]), 1

    return None


def _format_duration(delta: timedelta) -> str:
    total_seconds = int(delta.total_seconds())
    if total_seconds < 60:
        return f"{total_seconds}с"
    if total_seconds < 3600:
        return f"{total_seconds // 60}м"
    if total_seconds < 86400:
        return f"{total_seconds // 3600}ч {(total_seconds % 3600) // 60}м"
    return f"{total_seconds // 86400}д {(total_seconds % 86400) // 3600}ч"


async def _fire_reminder(
    reminder_id: int,
    fire_at: datetime,
    title: str,
    message: str,
    ntfy_config: NtfyConfig,
    store: ReminderStore,
) -> None:
    delay = (fire_at - datetime.now(timezone.utc)).total_seconds()
    if delay > 0:
        await asyncio.sleep(delay)

    logger.info("Firing reminder #%d: %s", reminder_id, title)
    await send_ntfy(
        url=ntfy_config.url,
        topic=ntfy_config.topic,
        user=ntfy_config.user,
        password=ntfy_config.password,
        title=title,
        message=message,
    )
    await store.mark_done(reminder_id)


def schedule_reminder(
    reminder_id: int,
    fire_at: datetime,
    title: str,
    message: str,
    ntfy_config: NtfyConfig,
    store: ReminderStore,
) -> asyncio.Task:
    return asyncio.create_task(
        _fire_reminder(reminder_id, fire_at, title, message, ntfy_config, store)
    )


async def restore_pending_reminders(
    ntfy_config: NtfyConfig, store: ReminderStore
) -> int:
    pending = await store.get_pending()
    now = datetime.now(timezone.utc)
    count = 0
    for r in pending:
        if r.fire_at <= now:
            # Overdue — fire immediately
            schedule_reminder(r.id, now, r.title, r.message, ntfy_config, store)
        else:
            schedule_reminder(r.id, r.fire_at, r.title, r.message, ntfy_config, store)
        count += 1
    if count:
        logger.info("Restored %d pending reminders", count)
    return count


async def command_remind(
    client: TelegramClient,
    message: types.Message,
    *,
    ntfy_config: NtfyConfig,
    store: ReminderStore,
    tz: tzinfo,
) -> None:
    raw = (message.message or "").strip()
    # Remove ".r " prefix
    after_cmd = re.sub(r"^\.r\s+", "", raw, count=1)
    if not after_cmd or after_cmd == raw:
        await reply_to(client, message, "Формат: .r <время> [текст]\nПримеры: .r 15m, .r 14:00, .r 2026-03-05 14:00")
        return

    tokens = after_cmd.split()
    parsed = _parse_time(tokens, tz)
    if parsed is None:
        await reply_to(client, message, "Не удалось разобрать время.\nПримеры: 15m, 2h, 1d, 14:00, 2026-03-05 14:00")
        return

    parsed_time, consumed = parsed
    remaining_text = " ".join(tokens[consumed:]).strip()

    # Get reminder text: inline text, or replied message
    reminder_text = remaining_text
    if not reminder_text:
        replied = await get_replied_message(client, message)
        if replied:
            sender_name = await get_sender_display_name(client, replied)
            text_part = replied.message or "[медиа]"
            reminder_text = f"От {sender_name}:\n{text_part}"
        else:
            reminder_text = "Напоминание"

    title = "Напоминание"
    fire_at = parsed_time.fire_at

    reminder_id = await store.add(fire_at, title, reminder_text)
    schedule_reminder(reminder_id, fire_at, title, reminder_text, ntfy_config, store)

    delta = fire_at - datetime.now(timezone.utc)
    confirm = f"Напомню {parsed_time.human} ({_format_duration(delta)})"
    await reply_to(client, message, confirm)

    try:
        await client.delete_messages(message.peer_id, [message.id], revoke=True)
    except Exception:
        pass
