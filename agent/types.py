from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from hashlib import sha1
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def build_run_id(product_key: str, iso_week: str) -> str:
    raw = f"{product_key}:{iso_week}".encode()
    return sha1(raw).hexdigest()


def current_iso_week(now: datetime | None = None) -> str:
    instant = now.astimezone(IST) if now else datetime.now(tz=IST)
    year, week, _ = instant.isocalendar()
    return f"{year}-W{week:02d}"


@dataclass(frozen=True)
class Window:
    iso_week: str
    start: date
    end: date
    weeks: int


def week_window(iso_week: str, weeks: int = 1) -> Window:
    year_str, week_str = iso_week.split("-W", maxsplit=1)
    year = int(year_str)
    week = int(week_str)
    week_start = date.fromisocalendar(year, week, 1)
    start = week_start - timedelta(weeks=max(0, weeks - 1))
    end = week_start + timedelta(days=6)
    return Window(iso_week=iso_week, start=start, end=end, weeks=weeks)
