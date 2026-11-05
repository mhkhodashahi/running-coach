"""User-scoped source rows used by deterministic dashboard chart functions."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


class DashboardDataRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def source_rows(self, user_id: int, day: date) -> dict[str, Any]:
        params = {"user_id": user_id, "day": day.isoformat()}
        activities = self._rows("SELECT id,date,type,distance,duration,pace,avg_hr,planned_intent "
                                "FROM activities WHERE user_id=:user_id AND date<=:day ORDER BY date,id", params)
        plans = self._rows("SELECT id,date,sport,intent,duration_min,status,linked_activity_id FROM plan_sessions "
                           "WHERE user_id=:user_id AND date<=:day", params)
        health = self._rows("SELECT date,sleep_duration,resting_hr,hrv FROM health_metrics "
                            "WHERE user_id=:user_id AND date<=:day ORDER BY date", params)
        run_ids = [int(row["id"]) for row in activities if "run" in str(row["type"]).lower()]
        points = self._by_activity(run_ids, "SELECT activity_id,distance_km,elapsed_seconds FROM activity_track_points "
                                   "WHERE activity_id IN ({ids}) AND distance_km IS NOT NULL "
                                   "AND elapsed_seconds IS NOT NULL ORDER BY activity_id,point_index")
        laps = self._by_activity(run_ids, "SELECT activity_id,distance,duration,pace FROM activity_laps "
                                 "WHERE activity_id IN ({ids}) ORDER BY activity_id,lap_index")
        return {"activities": activities, "plans": plans, "health": health, "points": points, "laps": laps}

    def _by_activity(self, identifiers: list[int], query: str) -> dict[int, list[dict[str, Any]]]:
        if not identifiers:
            return {}
        params = {f"id_{index}": identifier for index, identifier in enumerate(identifiers)}
        placeholders = ",".join(f":id_{index}" for index in range(len(identifiers)))
        rows = self._session.execute(text(query.format(ids=placeholders)), params).mappings()
        result: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            item = dict(row)
            result.setdefault(int(item.pop("activity_id")), []).append(item)
        return result

    def _rows(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        return [dict(row) for row in self._session.execute(text(query), params).mappings()]
