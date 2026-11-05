"""Persistence queries that assemble the metrics engine's raw inputs."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


class MetricsRepository:
    """Read user-scoped source rows; date semantics and metric logic stay in ``metrics``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def profile(self, user_id: int) -> dict[str, Any] | None:
        row = self._session.execute(
            text("SELECT id,max_hr,age FROM users WHERE id=:user_id"), {"user_id": user_id}
        ).mappings().first()
        return dict(row) if row else None

    def health_rows(self, user_id: int) -> list[dict[str, Any]]:
        rows = self._session.execute(
            text("SELECT date,resting_hr,hrv,sleep_duration FROM health_metrics "
                 "WHERE user_id=:user_id ORDER BY date"), {"user_id": user_id}
        ).mappings()
        return [dict(row) for row in rows]

    def activity_rows(self, user_id: int) -> list[dict[str, Any]]:
        rows = self._session.execute(
            text("SELECT id,date,type,duration,avg_hr FROM activities "
                 "WHERE user_id=:user_id ORDER BY date,id"), {"user_id": user_id}
        ).mappings()
        return [dict(row) for row in rows]

    def effort_ratings(self, user_id: int) -> dict[int, int]:
        has_table = self._session.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='activity_efforts'")
        ).first()
        if has_table is None:
            return {}
        rows = self._session.execute(
            text("SELECT e.activity_id,e.rpe FROM activity_efforts e JOIN activities a "
                 "ON a.id=e.activity_id WHERE a.user_id=:user_id"),
            {"user_id": user_id},
        )
        return {int(row[0]): int(row[1]) for row in rows}

    def track_points(self, activity_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
        if not activity_ids:
            return {}
        params = {f"id_{index}": value for index, value in enumerate(activity_ids)}
        placeholders = ",".join(f":id_{index}" for index in range(len(activity_ids)))
        rows = self._session.execute(
            text("SELECT activity_id,point_index,elapsed_seconds,heart_rate,timestamp "
                 f"FROM activity_track_points WHERE activity_id IN ({placeholders}) "
                 "ORDER BY activity_id,point_index"), params,
        ).mappings()
        result: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            result.setdefault(int(row["activity_id"]), []).append(dict(row))
        return result

    def legacy_comparison_rows(self, user_id: int) -> dict[str, Any]:
        activities = self._session.execute(
            text("SELECT date,type,distance,duration,avg_hr,aerobic_effect,anaerobic_effect "
                 "FROM activities WHERE user_id=:user_id"), {"user_id": user_id}
        ).mappings()
        health = self._session.execute(
            text("SELECT date,resting_hr,hrv,sleep_duration,sleep_score,body_battery,recovery_time "
                 "FROM health_metrics WHERE user_id=:user_id"), {"user_id": user_id}
        ).mappings()
        profile = self._session.execute(
            text("SELECT max_hr FROM users WHERE id=:user_id"), {"user_id": user_id}
        ).first()
        return {"activities": [dict(row) for row in activities], "health": [dict(row) for row in health],
                "max_hr": profile[0] if profile else None}
