"""Read-only Settings page metadata queries."""

from __future__ import annotations

from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session


class SettingsViewRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

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
