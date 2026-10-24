"""Local, consistent display formatting for the server-rendered UI."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo


def short_date(value: date | str) -> str:
    day = date.fromisoformat(value[:10]) if isinstance(value, str) else value
    return f"{day:%a} {day.day} {day:%b}"


def sync_time(value: str | None, today: date, timezone: str) -> str:
    if not value:
        return "Never synced"
    stamp = datetime.fromisoformat(value)
    local = (stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp).astimezone(ZoneInfo(timezone))
    return f"Synced {local:%H:%M}" if local.date() == today else f"Synced {short_date(local.date())}, {local:%H:%M}"


def duration_minutes(value: float | None) -> str | None:
    if value is None:
        return None
    minutes = round(value)
    hours, remaining = divmod(abs(minutes), 60)
    text = f"{hours}h {remaining:02d}m" if hours else f"{remaining}m"
    return f"-{text}" if minutes < 0 else text


def activity_duration(minutes: float | None) -> str | None:
    """Activity.duration is stored in minutes."""
    if minutes is None or minutes <= 0:
        return None
    return duration_minutes(minutes)


def activity_distance(kilometres: float | None) -> str | None:
    """Activity.distance is stored in kilometres."""
    if kilometres is None or kilometres <= 0:
        return None
    return f"{kilometres:.1f} km"


def sleep_hours(value: float | None) -> str | None:
    return duration_minutes(value * 60) if value is not None else None


def metric(value: float | None, unit: str = "", precision: int = 0) -> str | None:
    if value is None:
        return None
    number = f"{value:.{precision}f}"
    return f"{number} {unit}" if unit else number


def delta(value: float | None, baseline: float | None, unit: str) -> str | None:
    if value is None or baseline is None:
        return None
    if unit == "sleep":
        difference = round((value - baseline) * 60)
        amount = duration_minutes(abs(difference))
    else:
        difference = round(value - baseline)
        amount = f"{abs(difference)} {unit}" if unit else str(abs(difference))
    sign = "+" if difference > 0 else "-" if difference < 0 else ""
    return f"{sign}{amount} vs baseline"
