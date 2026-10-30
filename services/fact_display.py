"""Shared display formatting for facts shown to the athlete and coach."""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Any


def as_number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def pace(value: Any) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"\d+:[0-5]\d(?:\s*/km)?", value.strip()):
        return f"{value.strip().split()[0].removesuffix('/km')} /km"
    minutes = as_number(value)
    if minutes is None or minutes <= 0:
        return None
    seconds = round(minutes * 60)
    return f"{seconds // 60}:{seconds % 60:02d} /km"


def duration(value: Any) -> str | None:
    minutes = as_number(value)
    if minutes is None or minutes < 0:
        return None
    seconds = round(minutes * 60)
    if seconds >= 3600:
        return f"{seconds // 3600}:{(seconds % 3600) // 60:02d} h"
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def hours(value: Any) -> str | None:
    number = as_number(value)
    if number is None or number < 0:
        return None
    minutes = round(number * 60)
    return f"{minutes // 60}h {minutes % 60:02d}m"


def short_date(value: date | str) -> str:
    day = date.fromisoformat(value[:10]) if isinstance(value, str) else value
    return f"{day:%a} {day.day} {day:%b}"


def clock_time(value: datetime) -> str:
    return value.strftime("%H:%M")


def heart_rate(value: Any) -> str | None:
    number = as_number(value)
    return f"{round(number)} bpm" if number is not None and number > 0 else None


def milliseconds(value: Any) -> str | None:
    number = as_number(value)
    return f"{round(number)} ms" if number is not None and number > 0 else None


def percent(value: Any, *, signed: bool = False) -> str | None:
    number = as_number(value)
    return f"{number:+.1f}%" if signed and number is not None else f"{number:.1f}%" if number is not None else None


def ratio(value: Any) -> str | None:
    number = as_number(value)
    return f"{number:.2f}" if number is not None else None


def signed_delta(value: Any, unit: str) -> str | None:
    number = as_number(value)
    if number is None:
        return None
    rounded = round(number)
    prefix = "+" if rounded > 0 else "−" if rounded < 0 else ""
    return f"{prefix}{abs(rounded)} {unit}"


def score(value: Any, *, decimals: int = 0) -> str | None:
    number = as_number(value)
    return f"{number:.{decimals}f}/100" if number is not None and decimals else f"{round(number)}/100" if number is not None else None


def pace_difference(seconds: Any) -> str | None:
    number = as_number(seconds)
    return f"{round(number):+d} s/km" if number is not None else None


def heart_rate_difference(bpm: Any) -> str | None:
    number = as_number(bpm)
    return f"{round(number):+d} bpm" if number is not None else None
