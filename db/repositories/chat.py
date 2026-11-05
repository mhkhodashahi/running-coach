"""Persistence for user-scoped coach chat history."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


class ChatRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def recent_turns(self, user_id: int, limit: int) -> list[dict[str, Any]]:
        rows = self._session.execute(
            text("SELECT question,answer,evidence_json,activity_ids_json,created_at,tool_calls_json "
                 "FROM coach_chat_turns WHERE user_id=:user_id ORDER BY id DESC LIMIT :limit"),
            {"user_id": user_id, "limit": limit},
        ).mappings()
        return [dict(row) for row in reversed(list(rows))]
