"""Persistence for athlete-owned timeline notes."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


class TimelineNoteRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_between(self, user_id: int, start: date, end: date, limit: int = 500) -> tuple[dict[str, Any], ...]:
        rows = self._session.execute(
            text("SELECT id,date,text FROM timeline_notes WHERE user_id=:user_id "
                 "AND date BETWEEN :start AND :end ORDER BY date,id LIMIT :limit"),
            {"user_id": user_id, "start": start.isoformat(), "end": end.isoformat(), "limit": limit},
        ).mappings()
        return tuple(dict(row) for row in rows)

    def save(self, user_id: int, day: date, text_value: str, now: datetime,
             note_id: int | None = None) -> int:
        if note_id is None:
            result = self._session.execute(
                text("INSERT INTO timeline_notes(user_id,date,text,created_at,updated_at) "
                     "VALUES(:user_id,:date,:text,:now,:now)"),
                {"user_id": user_id, "date": day.isoformat(), "text": text_value, "now": now},
            )
            return int(result.lastrowid or 0)
        result = self._session.execute(
            text("UPDATE timeline_notes SET date=:date,text=:text,updated_at=:now "
                 "WHERE id=:id AND user_id=:user_id"),
            {"date": day.isoformat(), "text": text_value, "now": now,
             "id": note_id, "user_id": user_id},
        )
        if result.rowcount != 1:
            raise ValueError("Note not found")
        return note_id

    def delete(self, user_id: int, note_id: int) -> bool:
        result = self._session.execute(
            text("DELETE FROM timeline_notes WHERE id=:id AND user_id=:user_id"),
            {"id": note_id, "user_id": user_id},
        )
        return result.rowcount == 1
