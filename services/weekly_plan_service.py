"""Read-only plan views shared by Today, Telegram and coach tools."""

from __future__ import annotations

from datetime import date
from typing import Any

from coach.proposals import get_week, monday
from config import Settings, get_settings
from db.repositories.plan import PlanRepository
from db.session import session_scope


def get_weekly_plan(start: date, *, settings: Settings | None = None,
                    user_id: int | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    return get_week(settings.db_path, user_id or settings.default_user_id, monday(start))


def scheduled_team_sports(day: date, *, settings: Settings | None = None,
                          user_id: int | None = None) -> tuple[str, ...]:
    """Read recurring commitments and dated team sessions without materializing them."""
    settings = settings or get_settings()
    identifier = user_id or settings.default_user_id
    url = f"sqlite:///file:{settings.db_path.resolve()}?mode=ro&uri=true"
    with session_scope(url) as session:
        return PlanRepository(session).scheduled_team_sports(identifier, day)


def todays_sessions(day: date, *, settings: Settings | None = None,
                    user_id: int | None = None) -> list[dict[str, Any]]:
    plan = get_weekly_plan(day, settings=settings, user_id=user_id)
    return [item for item in plan["sessions"] if item["date"] == day.isoformat()]
