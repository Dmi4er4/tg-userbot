import asyncio
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Reminder:
    id: int
    fire_at: datetime  # UTC
    title: str
    message: str
    created_at: datetime


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS reminders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    fire_at    TEXT NOT NULL,
    title      TEXT NOT NULL,
    message    TEXT NOT NULL,
    done       INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
)
"""


class ReminderStore:
    def __init__(self, db_path: str = "/data/reminders.db") -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(_CREATE_TABLE)
        self._conn.commit()

    async def add(self, fire_at: datetime, title: str, message: str) -> int:
        def _insert() -> int:
            cur = self._conn.execute(
                "INSERT INTO reminders (fire_at, title, message, created_at) VALUES (?, ?, ?, ?)",
                (
                    fire_at.astimezone(timezone.utc).isoformat(),
                    title,
                    message,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            self._conn.commit()
            return cur.lastrowid  # type: ignore[return-value]

        return await asyncio.to_thread(_insert)

    async def get_pending(self) -> list[Reminder]:
        def _select() -> list[Reminder]:
            rows = self._conn.execute(
                "SELECT id, fire_at, title, message, created_at FROM reminders WHERE done = 0"
            ).fetchall()
            return [
                Reminder(
                    id=r[0],
                    fire_at=datetime.fromisoformat(r[1]),
                    title=r[2],
                    message=r[3],
                    created_at=datetime.fromisoformat(r[4]),
                )
                for r in rows
            ]

        return await asyncio.to_thread(_select)

    async def mark_done(self, reminder_id: int) -> None:
        def _update() -> None:
            self._conn.execute(
                "UPDATE reminders SET done = 1 WHERE id = ?", (reminder_id,)
            )
            self._conn.commit()

        await asyncio.to_thread(_update)

    def close(self) -> None:
        self._conn.close()
