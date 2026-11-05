"""Transactional persistence for coach call limits and chat history."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session


class AgentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def consume_call(self, user_id: int, local_day: date, daily_limit: int,
                     created_at: datetime) -> bool:
        """Atomically reserve one call; concurrent requests cannot exceed the cap."""
        self._session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        count = self._session.execute(
            text("SELECT COUNT(*) FROM coach_llm_calls WHERE user_id=:user_id AND local_day=:day"),
            {"user_id": user_id, "day": local_day.isoformat()},
        ).scalar_one()
        if count >= daily_limit:
            return False
        self._session.execute(
            text("INSERT INTO coach_llm_calls(user_id,local_day,created_at) "
                 "VALUES(:user_id,:day,:created_at)"),
            {"user_id": user_id, "day": local_day.isoformat(),
             "created_at": created_at.replace(tzinfo=None).isoformat()},
        )
        return True

    def call_count(self, user_id: int, local_day: date) -> int:
        return int(self._session.execute(
            text("SELECT COUNT(*) FROM coach_llm_calls WHERE user_id=:user_id AND local_day=:day"),
            {"user_id": user_id, "day": local_day.isoformat()},
        ).scalar_one())

    def save_chat_turn(self, user_id: int, question: str, answer: str, evidence: str,
                       activity_ids: str, tool_calls: str, provider: str, model: str,
                       prompt_version: str, created_at: datetime) -> int:
        result = self._session.execute(
            text("INSERT INTO coach_chat_turns(user_id,question,answer,evidence_json,activity_ids_json,"
                 "tool_calls_json,model_provider,model_name,prompt_version,created_at) "
                 "VALUES(:user_id,:question,:answer,:evidence,:activity_ids,:tool_calls,:provider,:model,"
                 ":prompt_version,:created_at)"),
            {"user_id": user_id, "question": question, "answer": answer, "evidence": evidence,
             "activity_ids": activity_ids, "tool_calls": tool_calls, "provider": provider,
             "model": model, "prompt_version": prompt_version,
             "created_at": created_at.replace(tzinfo=None).isoformat()},
        )
        return int(result.lastrowid or 0)
