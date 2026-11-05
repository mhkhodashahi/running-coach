"""Read-only persistence for worker health checks."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


class WorkerHealthRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def sync_time(self, user_id: int) -> str | None:
        return self._session.execute(text(
            "SELECT last_synced_at FROM garmin_sync_status WHERE user_id=:user_id"),
            {"user_id": user_id}).scalar_one_or_none()

    def recent_jobs(self, user_id: int, *, exclude_prefix: str) -> list[dict[str, Any]]:
        rows = self._session.execute(text(
            "SELECT job,status FROM job_runs WHERE user_id=:user_id AND status!='sending' "
            "AND job NOT LIKE :exclude ORDER BY started_at DESC,id DESC"),
            {"user_id": user_id, "exclude": f"{exclude_prefix}%"}).mappings()
        return [dict(row) for row in rows]

    def job_status(self, user_id: int, job: str, day: date) -> str | None:
        return self._session.execute(text(
            "SELECT status FROM job_runs WHERE user_id=:user_id AND job=:job AND run_date=:day"),
            {"user_id": user_id, "job": job, "day": day.isoformat()}).scalar_one_or_none()

    def latest_finished(self, user_id: int) -> str | None:
        return self._session.execute(text(
            "SELECT MAX(finished_at) FROM job_runs WHERE user_id=:user_id"),
            {"user_id": user_id}).scalar_one_or_none()
