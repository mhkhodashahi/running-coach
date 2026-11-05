"""Read models used to render the weekly training plan."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


class PlanViewRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def actual_activities(self, user_id: int, start: date, end: date) -> list[dict[str, Any]]:
        rows = self._session.execute(text(
            "SELECT id,date,type,duration FROM activities WHERE user_id=:user_id "
            "AND substr(date,1,10) BETWEEN :start AND :end ORDER BY date,id"),
            {"user_id": user_id, "start": start.isoformat(), "end": end.isoformat()}).mappings()
        return [dict(row) for row in rows]

    def athlete_rest_days(self, user_id: int, start: date, end: date) -> set[str]:
        rows = self._session.execute(text(
            "SELECT decision_date,payload_json FROM coaching_decisions WHERE user_id=:user_id "
            "AND decision_type='daily_v2' AND decision_date BETWEEN :start AND :end"),
            {"user_id": user_id, "start": start.isoformat(), "end": end.isoformat()}).mappings()
        import json

        result = set()
        for row in rows:
            try:
                if json.loads(row["payload_json"]).get("athlete_choice") == "rest":
                    result.add(row["decision_date"])
            except (ValueError, TypeError):
                continue
        return result

    def latest_undo_snapshot(self, user_id: int) -> str | None:
        return self._session.execute(text(
            "SELECT snapshot_json FROM plan_snapshots WHERE user_id=:user_id AND undone_at IS NULL "
            "ORDER BY id DESC LIMIT 1"), {"user_id": user_id}).scalar_one_or_none()
