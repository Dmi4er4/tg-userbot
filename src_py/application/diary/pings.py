from typing import Callable

PingFormatter = Callable[[float], str]
PingEntry = tuple[int, str, PingFormatter]


def _week_msg(_remaining: float) -> str:
    return "⏳ Diary release в течение недели. Reset: .diary-delay"


def _day_msg_factory(hours: int) -> PingFormatter:
    def fmt(_remaining: float) -> str:
        return f"⏳ Diary release сегодня. Осталось ~{hours}h. Reset: .diary-delay"

    return fmt


def _hour_msg_factory(minutes: int) -> PingFormatter:
    def fmt(_remaining: float) -> str:
        return f"⚠️ Diary release через {minutes}m. Reset: .diary-delay"

    return fmt


def _ten_msg_factory(minutes: int) -> PingFormatter:
    def fmt(_remaining: float) -> str:
        return f"🚨 Diary release через {minutes}m. Reset: .diary-delay"

    return fmt


def build_ping_table() -> list[PingEntry]:
    table: list[PingEntry] = []
    table.append((7 * 86400, "week", _week_msg))
    for h in range(24, 1, -1):  # 24..2
        table.append((h * 3600, f"day:{h}", _day_msg_factory(h)))
    for m in range(60, 10, -10):  # 60,50,40,30,20
        table.append((m * 60, f"hour:{m}", _hour_msg_factory(m)))
    for m in range(10, 0, -1):  # 10..1
        table.append((m * 60, f"10min:{m}", _ten_msg_factory(m)))
    table.sort(key=lambda x: -x[0])
    return table
