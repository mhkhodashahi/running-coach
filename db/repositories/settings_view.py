"""User-scoped settings reads and goal state changes."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from db.models import Goal, User


class SettingsViewRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def profile(self, user_id: int) -> User | None:
        return self._session.get(User, user_id)

    def owned_goal(self, user_id: int, goal_id: int) -> Goal | None:
        return self._session.scalar(select(Goal).where(Goal.id == goal_id, Goal.user_id == user_id))

    def archive_goal(self, user_id: int, goal_id: int) -> None:
        goal = self.owned_goal(user_id, goal_id)
        if goal is None:
            raise ValueError("Goal not found")
        goal.status = "archived"
        goal.is_active = False
        self._session.flush()

    def calls_today(self, user_id: int, day: date) -> int:
        return int(self._session.execute(text(
            "SELECT COUNT(*) FROM coach_llm_calls WHERE user_id=:user_id AND local_day=:day"),
            {"user_id": user_id, "day": day.isoformat()}).scalar_one())

    def backup_status(self, user_id: int, day: str | None) -> str | None:
        if not day:
            return None
        return self._session.execute(text(
            "SELECT status FROM job_runs WHERE user_id=:user_id AND job='daily_backup' AND run_date=:day"),
            {"user_id": user_id, "day": day}).scalar_one_or_none()
