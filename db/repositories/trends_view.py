"""Persistence for cached trend summaries and comparison-series source rows."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


class TrendsViewRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def cached_summary(self, user_id: int, day: date, decision_type: str) -> str | None:
        return self._session.execute(text(
            "SELECT payload_json FROM coaching_decisions WHERE user_id=:user_id AND decision_date=:day "
            "AND decision_type=:kind ORDER BY id DESC LIMIT 1"),
            {"user_id": user_id, "day": day.isoformat(), "kind": decision_type}).scalar_one_or_none()

    def save_summary(self, user_id: int, day: date, decision_type: str, headline: str,
                     payload_json: str, created_at: datetime) -> None:
        self._session.execute(text(
            "INSERT INTO coaching_decisions(user_id,decision_type,decision_date,summary,risk_level,payload_json,created_at) "
            "VALUES(:user_id,:kind,:day,:summary,'moderate',:payload,:created_at)"),
            {"user_id": user_id, "kind": decision_type, "day": day.isoformat(), "summary": headline,
             "payload": payload_json, "created_at": created_at})

    def insight_inputs(self, user_id: int, start: date, end: date) -> dict[str, Any]:
        goal = self._session.execute(text(
            "SELECT goal_type,target_distance_km FROM goals WHERE user_id=:user_id AND is_active=1 "
            "ORDER BY id DESC LIMIT 1"), {"user_id": user_id}).mappings().first()
        runs = self._session.execute(text(
            "SELECT date,type,distance,duration FROM activities WHERE user_id=:user_id "
            "AND date BETWEEN :start AND :end"),
            {"user_id": user_id, "start": start.isoformat(), "end": end.isoformat()}).mappings()
        previous_start = start.fromordinal(start.toordinal() - (end - start).days - 1)
        previous_end = start.fromordinal(start.toordinal() - 1)
        previous = self._session.execute(text(
            "SELECT date,resting_hr,hrv,sleep_duration FROM health_metrics WHERE user_id=:user_id "
            "AND date BETWEEN :start AND :end"),
            {"user_id": user_id, "start": previous_start.isoformat(), "end": previous_end.isoformat()}).mappings()
        return {"goal": dict(goal) if goal else None, "runs": [dict(row) for row in runs],
                "previous_health": [dict(row) for row in previous]}
