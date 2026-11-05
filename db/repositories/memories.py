"""Persistence boundary for coach memories and their audit history."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


class CoachMemoryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_for_user(self, user_id: int, status: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"user_id": user_id}
        filter_sql = ""
        if status:
            filter_sql = " AND status=:status"
            params["status"] = status
        rows = self._session.execute(text(
            "SELECT * FROM coach_memories WHERE user_id=:user_id" + filter_sql +
            " ORDER BY rule_json IS NOT NULL DESC,created_at DESC"), params).mappings()
        return [dict(row) for row in rows]

    def active_text_exists(self, user_id: int, value: str, today: date,
                           exclude_id: int | None = None, *, effective_date: bool = True) -> bool:
        extra = " AND id!=:exclude_id" if exclude_id is not None else ""
        expiry = " AND (valid_until IS NULL OR valid_until>=:today)" if effective_date else ""
        params: dict[str, Any] = {"user_id": user_id, "text": value, "today": today.isoformat()}
        if exclude_id is not None:
            params["exclude_id"] = exclude_id
        return self._session.execute(text(
            "SELECT 1 FROM coach_memories WHERE user_id=:user_id AND status='active' "
            "AND lower(trim(text))=lower(trim(:text))" + extra + expiry + " LIMIT 1"), params).first() is not None

    def get(self, user_id: int, memory_id: int, *, status: str | None = None) -> dict[str, Any] | None:
        condition = " AND status=:status" if status else ""
        params: dict[str, Any] = {"user_id": user_id, "id": memory_id}
        if status:
            params["status"] = status
        row = self._session.execute(text(
            "SELECT * FROM coach_memories WHERE id=:id AND user_id=:user_id" + condition), params).mappings().first()
        return dict(row) if row else None

    def insert(self, user_id: int, *, category: str, text_value: str, rule_json: str | None,
               status: str, source: str, valid_from: date, valid_until: date | None,
               now: datetime, suggestion_action: str | None, target_memory_id: int | None,
               suggestion_reason: str | None) -> int:
        result = self._session.execute(text(
            "INSERT INTO coach_memories(user_id,category,text,rule_json,status,source,valid_from,valid_until,"
            "created_at,updated_at,suggestion_action,target_memory_id,suggestion_reason) "
            "VALUES(:user_id,:category,:text,:rule,:status,:source,:valid_from,:valid_until,:now,:now,"
            ":action,:target,:reason)"),
            {"user_id": user_id, "category": category, "text": text_value, "rule": rule_json,
             "status": status, "source": source, "valid_from": valid_from.isoformat(),
             "valid_until": valid_until.isoformat() if valid_until else None, "now": now,
             "action": suggestion_action, "target": target_memory_id, "reason": suggestion_reason})
        return int(result.lastrowid or 0)

    def update(self, user_id: int, memory_id: int, values: dict[str, Any], now: datetime) -> None:
        self._session.execute(text(
            "UPDATE coach_memories SET category=:category,text=:text,rule_json=:rule,valid_until=:valid_until,"
            "updated_at=:now WHERE id=:id AND user_id=:user_id"),
            {**values, "id": memory_id, "user_id": user_id, "now": now,
             "valid_until": values["valid_until"].isoformat() if values.get("valid_until") else None})

    def set_status(self, user_id: int, memory_id: int, status: str, now: datetime) -> None:
        self._session.execute(text("UPDATE coach_memories SET status=:status,updated_at=:now "
                                   "WHERE id=:id AND user_id=:user_id"),
                              {"status": status, "now": now, "id": memory_id, "user_id": user_id})

    def add_history(self, memory_id: int, old: dict[str, Any], now: datetime, reason: str) -> None:
        self._session.execute(text(
            "INSERT INTO coach_memory_history(memory_id,previous_text,previous_rule_json,previous_status,"
            "changed_at,change_reason) VALUES(:id,:text,:rule,:status,:now,:reason)"),
            {"id": memory_id, "text": old["text"], "rule": old.get("rule_json"), "status": old["status"],
             "now": now, "reason": reason[:200]})

    def delete(self, user_id: int, memory_id: int) -> None:
        self._session.execute(text("DELETE FROM coach_memories WHERE id=:id AND user_id=:user_id"),
                              {"id": memory_id, "user_id": user_id})

    def touch_used(self, memory_ids: list[int], now: datetime) -> None:
        for memory_id in memory_ids:
            self._session.execute(text("UPDATE coach_memories SET last_used_at=:now "
                                       "WHERE id=:id AND status='active'"), {"now": now, "id": memory_id})

    def resolve_suggestion(self, user_id: int, suggestion_id: int, operation: str,
                            final_text: str, final_category: str, final_rule_json: str | None,
                            valid_until: date | None, now: datetime) -> str:
        suggestion = self.get(user_id, suggestion_id, status="suggested")
        if suggestion is None:
            raise ValueError("Suggestion not found")
        if operation in {"UPDATE", "DEACTIVATE"}:
            target = self.get(user_id, suggestion["target_memory_id"], status="active")
            if target is None:
                raise ValueError("The memory this suggestion refers to is no longer active")
            if operation == "UPDATE" and self.active_text_exists(
                    user_id, final_text, date.today(), target["id"], effective_date=False):
                raise ValueError("An active memory with the same text already exists")
            self.add_history(target["id"], target, now, "coach suggestion kept")
            if operation == "DEACTIVATE":
                self.set_status(user_id, target["id"], "inactive", now)
            else:
                replacement_rule = (target["rule_json"] if suggestion["rule_json"] is None and
                                    target["rule_json"] else final_rule_json)
                self.update(user_id, target["id"], {"category": final_category, "text": final_text,
                             "rule": replacement_rule, "valid_until": valid_until or suggestion["valid_until"]}, now)
        elif operation == "ADD":
            if self.active_text_exists(user_id, final_text, date.today(), suggestion_id,
                                       effective_date=False):
                raise ValueError("An active memory with the same text already exists")
            self.add_history(suggestion_id, suggestion, now, "coach suggestion kept")
            self.update(user_id, suggestion_id, {"category": final_category, "text": final_text,
                         "rule": final_rule_json, "valid_until": valid_until or suggestion["valid_until"]}, now)
            self.set_status(user_id, suggestion_id, "active", now)
            return operation
        else:
            raise ValueError("Unknown suggestion action")
        self.add_history(suggestion_id, suggestion, now, "suggestion resolved")
        self.set_status(user_id, suggestion_id, "inactive", now)
        return operation
