"""Formatting helpers for UI output."""

from __future__ import annotations

import math


def format_pace(minutes_per_km: float | None) -> str:
    if minutes_per_km is None:
        return "n/a"
    total_seconds = int(round(minutes_per_km * 60))
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d} /km"


def format_duration_minutes(duration_minutes: float | None) -> str:
    if duration_minutes is None:
        return "n/a"
    hours = int(duration_minutes // 60)
    minutes = int(round(duration_minutes % 60))
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"


def format_goal_time(total_minutes: float | None) -> str:
    if total_minutes is None:
        return "n/a"
    total_seconds = int(round(total_minutes * 60))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def format_gap_minutes(gap_minutes: float) -> str:
    sign = "+" if gap_minutes >= 0 else "-"
    return f"{sign}{abs(gap_minutes):.1f} min"


def format_metric_number(value: float | int | None, *, decimals: int = 0, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if math.isnan(numeric):
        return "n/a"
    return f"{numeric:.{decimals}f}{suffix}"
