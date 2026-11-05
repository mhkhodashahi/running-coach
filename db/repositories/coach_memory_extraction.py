"""Persistence cursor and bounded chat batches for idle memory extraction."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


class CoachMemoryExtractionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

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
