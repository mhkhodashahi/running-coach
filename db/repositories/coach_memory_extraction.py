"""Persistence cursor and bounded chat batches for idle memory extraction."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


class CoachMemoryExtractionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def training_responses(self, user_id: int, through: date) -> list[dict[str, Any]]:
        """Return repeated, linked and rated sessions; absent next-day health stays unknown."""
        rows = self._session.execute(text(
            "SELECT a.date, p.sport, p.intent, p.duration_min AS planned_min, a.duration AS actual_min, "
            "e.rpe, h.resting_hr AS next_day_resting_hr, h.hrv AS next_day_hrv, "
            "(SELECT group_concat(DISTINCT lower(prev.type)) FROM activities prev "
            "WHERE prev.user_id=a.user_id AND prev.date=date(a.date,'-1 day')) AS previous_day_sports "
            "FROM plan_sessions p JOIN activities a ON a.id=p.linked_activity_id AND a.user_id=p.user_id "
            "JOIN activity_efforts e ON e.activity_id=a.id "
            "LEFT JOIN health_metrics h ON h.user_id=a.user_id AND h.date=date(a.date,'+1 day') "
            "AND h.date<=:through WHERE p.user_id=:user AND a.date BETWEEN :start AND :through "
            "ORDER BY a.date DESC, a.id DESC LIMIT 40"),
            {"user": user_id, "start": through - timedelta(days=55), "through": through}).mappings().all()
        days: dict[tuple[str, str], set[str]] = {}
        for row in rows:
            days.setdefault((row["sport"], row["intent"]), set()).add(row["date"])
        return [dict(row) for row in rows if len(days[row["sport"], row["intent"]]) >= 2]

    def next_batch(self, user_id: int, limit: int = 20) -> tuple[int, list[dict[str, Any]]]:
        cursor = self._session.execute(text(
            "SELECT processed_through_id FROM coach_memory_extraction_state WHERE user_id=:user_id"),
            {"user_id": user_id}).scalar_one_or_none()
        rows = self._session.execute(text(
            "SELECT id,question,answer,created_at FROM coach_chat_turns WHERE user_id=:user_id AND id>:cursor "
            "ORDER BY id LIMIT :limit"),
            {"user_id": user_id, "cursor": int(cursor or 0), "limit": limit}).mappings()
        return int(cursor or 0), [dict(row) for row in rows]

    def advance(self, user_id: int, processed_through_id: int, updated_at: datetime) -> None:
        self._session.execute(text(
            "INSERT INTO coach_memory_extraction_state(user_id,processed_through_id,updated_at) "
            "VALUES(:user_id,:cursor,:updated_at) ON CONFLICT(user_id) DO UPDATE SET "
            "processed_through_id=excluded.processed_through_id,updated_at=excluded.updated_at"),
            {"user_id": user_id, "cursor": processed_through_id,
             "updated_at": updated_at.replace(tzinfo=None).isoformat()})
