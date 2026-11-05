"""Bounded read models for the Today screen."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


class TodayViewRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def sync_time(self, user_id: int) -> str | None:
        return self._session.execute(text(
            "SELECT last_synced_at FROM garmin_sync_status WHERE user_id=:user_id"),
            {"user_id": user_id}).scalar_one_or_none()

    def health_context(self, user_id: int, health_day: date, activity_before: date,
                       activity_day: date) -> dict[str, Any]:
        key = {"user_id": user_id, "day": health_day.isoformat()}
        body_battery = self._session.execute(text(
            "SELECT body_battery FROM health_metrics WHERE user_id=:user_id AND date=:day"), key).scalar_one_or_none()
        body_history = self._rows(
            "SELECT body_battery FROM health_metrics WHERE user_id=:user_id AND date>=:start AND date<:day "
            "AND body_battery IS NOT NULL",
            {**key, "start": (health_day - timedelta(days=7)).isoformat()})
        trend_rows = self._rows(
            "SELECT resting_hr,hrv,sleep_duration,body_battery FROM health_metrics WHERE user_id=:user_id "
            "AND date<=:day ORDER BY date DESC LIMIT 7", key)
        activities = self._rows(
            "SELECT id,date,type,distance,duration,avg_hr FROM activities WHERE user_id=:user_id AND date<:before "
            "ORDER BY date DESC,id DESC", {"user_id": user_id, "before": activity_before.isoformat()})
        recent = self._rows(
            "SELECT a.id,a.date,a.type,a.duration,(SELECT MIN(p.timestamp) FROM activity_track_points p "
            "WHERE p.activity_id=a.id) AS started_at,i.payload_json,i.schema_version FROM activities a "
            "LEFT JOIN activity_coaching_insights i ON i.activity_id=a.id AND i.user_id=a.user_id "
            "WHERE a.user_id=:user_id AND a.date>=:start AND a.date<=:day "
            "ORDER BY a.date DESC,a.id DESC LIMIT 20",
            {"user_id": user_id, "start": (activity_day - timedelta(days=2)).isoformat(),
             "day": activity_day.isoformat()})
        return {"body_battery": body_battery, "body_history": body_history,
                "trend_rows": trend_rows, "activities": activities, "recent_sessions": recent}

    def _rows(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        return [dict(row) for row in self._session.execute(text(query), params).mappings()]
