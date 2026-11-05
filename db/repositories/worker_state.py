"""Persistence for scheduled-message settings and idempotent job runs."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


class WorkerStateRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def preferences(self, user_id: int) -> dict[str, Any] | None:
        row = self._session.execute(text(
            "SELECT * FROM notification_settings WHERE user_id=:user_id"),
            {"user_id": user_id}).mappings().first()
        return dict(row) if row else None

    def save_preferences(self, user_id: int, fields: dict[str, Any], values: dict[str, Any]) -> None:
        columns = ",".join(fields)
        binds = ",".join(f":{field}" for field in fields)
        updates = ",".join(f"{field}=excluded.{field}" for field in fields)
        params = {"user_id": user_id, **{field: values[field] for field in fields}}
        self._session.execute(text(
            f"INSERT INTO notification_settings(user_id,{columns}) VALUES(:user_id,{binds}) "
            f"ON CONFLICT(user_id) DO UPDATE SET {updates}"), params)

    def claim(self, user_id: int, job: str, day: date, now: datetime) -> bool:
        result = self._session.execute(text(
            "INSERT OR IGNORE INTO job_runs(user_id,job,run_date,status,started_at,attempts) "
            "VALUES(:user_id,:job,:day,'sending',:started_at,1)"),
            {"user_id": user_id, "job": job, "day": day.isoformat(),
             "started_at": now.isoformat()})
        return result.rowcount == 1

    def finish(self, user_id: int, job: str, day: date, now: datetime,
               status: str, message: str | None, error: str | None) -> None:
        self._session.execute(text(
            "UPDATE job_runs SET status=:status,finished_at=:finished_at,error=:error,message_text=:message "
            "WHERE user_id=:user_id AND job=:job AND run_date=:day"),
            {"user_id": user_id, "job": job, "day": day.isoformat(), "status": status,
             "finished_at": now.isoformat(), "error": error, "message": message})

    def history(self, user_id: int, limit: int) -> list[dict[str, Any]]:
        rows = self._session.execute(text(
            "SELECT job,run_date,status,started_at,finished_at,error,message_text FROM job_runs "
            "WHERE user_id=:user_id ORDER BY started_at DESC,id DESC LIMIT :limit"),
            {"user_id": user_id, "limit": limit}).mappings()
        return [dict(row) for row in rows]


class WorkerJobReadRepository:
    """Small read queries shared by the scheduler and its health checks."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def health_ready(self, user_id: int, day: date) -> bool:
        row = self._session.execute(text(
            "SELECT sleep_duration,hrv FROM health_metrics WHERE user_id=:user_id AND date=:day"),
            {"user_id": user_id, "day": day.isoformat()}).first()
        return bool(row and row[0] is not None and row[1] is not None)

    def day_activities(self, user_id: int, day: date) -> list[dict[str, Any]]:
        rows = self._session.execute(text(
            "SELECT a.id,a.type,a.duration,e.rpe FROM activities a "
            "LEFT JOIN activity_efforts e ON e.activity_id=a.id "
            "WHERE a.user_id=:user_id AND a.date=:day ORDER BY a.id"),
            {"user_id": user_id, "day": day.isoformat()}).mappings()
        return [dict(row) for row in rows]

    def activity_types(self, user_id: int, start: date, end: date) -> dict[int, str]:
        rows = self._session.execute(text(
            "SELECT id,type FROM activities WHERE user_id=:user_id AND date>=:start AND date<=:end"),
            {"user_id": user_id, "start": start.isoformat(), "end": end.isoformat()})
        return {int(row[0]): str(row[1]) for row in rows}

    def latest_health_day(self, user_id: int, day: date) -> str | None:
        return self._session.execute(text(
            "SELECT MAX(date) FROM health_metrics WHERE user_id=:user_id AND date<=:day "
            "AND hrv IS NOT NULL AND resting_hr IS NOT NULL"),
            {"user_id": user_id, "day": day.isoformat()}).scalar_one_or_none()

    def pending_running_opinions(self, user_id: int, start: date, end: date) -> list[tuple[int, date]]:
        rows = self._session.execute(text(
            "SELECT a.id,a.date FROM activities a LEFT JOIN activity_coaching_insights i "
            "ON i.activity_id=a.id WHERE a.user_id=:user_id AND a.date>=:start AND a.date<=:end "
            "AND lower(a.type) LIKE '%running%' AND i.id IS NULL ORDER BY a.id"),
            {"user_id": user_id, "start": start.isoformat(), "end": end.isoformat()})
        return [(int(row[0]), date.fromisoformat(str(row[1])[:10])) for row in rows]

    def has_job(self, user_id: int, job: str, day: date) -> bool:
        return self._session.execute(text(
            "SELECT 1 FROM job_runs WHERE user_id=:user_id AND job=:job AND run_date=:day"),
            {"user_id": user_id, "job": job, "day": day.isoformat()}).first() is not None

    def job_message(self, user_id: int, job: str, day: date) -> dict[str, Any] | None:
        row = self._session.execute(text(
            "SELECT status,message_text FROM job_runs WHERE user_id=:user_id AND job=:job AND run_date=:day"),
            {"user_id": user_id, "job": job, "day": day.isoformat()}).mappings().first()
        return dict(row) if row else None

    def has_completed_sync_today(self, user_id: int, day: date) -> bool:
        return self._session.execute(text(
            "SELECT 1 FROM job_runs WHERE user_id=:user_id AND run_date=:day "
            "AND job LIKE 'sync-%' AND status='done' LIMIT 1"),
            {"user_id": user_id, "day": day.isoformat()}).first() is not None
