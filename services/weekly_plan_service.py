"""Read-only plan views shared by Today, Telegram and coach tools."""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from coach.proposals import get_week, monday
from config import Settings, get_settings


def get_weekly_plan(start: date, *, settings: Settings | None = None,
                    user_id: int | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    return get_week(settings.db_path, user_id or settings.default_user_id, monday(start))


def scheduled_team_sports(day: date, *, settings: Settings | None = None,
                          user_id: int | None = None) -> tuple[str, ...]:
    """Read recurring commitments and dated team sessions without materializing them."""
    settings = settings or get_settings()
    identifier = user_id or settings.default_user_id
    with sqlite3.connect(settings.db_path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        fixed = connection.execute(
            "SELECT f.sport FROM fixed_commitments f WHERE f.user_id=? AND f.weekday=? AND f.active=1 "
            "AND NOT EXISTS (SELECT 1 FROM plan_sessions p WHERE p.user_id=f.user_id "
            "AND p.fixed_commitment_id=f.id AND p.date=? AND p.status='skipped')",
            (identifier, day.weekday(), day.isoformat())).fetchall()
        planned = connection.execute("SELECT sport FROM plan_sessions WHERE user_id=? AND date=? "
                                     "AND sport IN ('football','volleyball') AND status='planned'",
                                     (identifier, day.isoformat())).fetchall()
    return tuple(dict.fromkeys(row[0] for row in (*fixed, *planned)))


def todays_sessions(day: date, *, settings: Settings | None = None,
                    user_id: int | None = None) -> list[dict[str, Any]]:
    plan = get_weekly_plan(day, settings=settings, user_id=user_id)
    return [item for item in plan["sessions"] if item["date"] == day.isoformat()]
