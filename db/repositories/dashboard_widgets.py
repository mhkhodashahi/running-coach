"""Atomic persistence for each user's ordered dashboard widget layout."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session


class DashboardWidgetRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list(self, user_id: int) -> list[dict]:
        rows = self._session.execute(text(
            "SELECT id,chart_id,config_json,created_at FROM dashboard_widgets "
            "WHERE user_id=:user_id ORDER BY position"), {"user_id": user_id}).mappings()
        return [dict(row) for row in rows]

    def replace(self, user_id: int, widgets: list[dict], now: datetime) -> list[dict]:
        old = {int(row["id"]): row["created_at"] for row in self.list(user_id) if row["id"] is not None}
        next_id = int(self._session.execute(text(
            "SELECT COALESCE(MAX(id),0)+1 FROM dashboard_widgets")).scalar_one())
        self._session.execute(text("DELETE FROM dashboard_widgets WHERE user_id=:user_id"), {"user_id": user_id})
        if not widgets:
            self._session.execute(text(
                "INSERT INTO dashboard_widgets(user_id,position,chart_id,config_json,created_at,updated_at) "
                "VALUES(:user_id,0,'__empty__','{}',:now,:now)"), {"user_id": user_id, "now": now})
        saved = []
        for position, widget in enumerate(widgets):
            identifier = widget.get("id")
            created = old.get(identifier, now)
            if identifier not in old:
                identifier = next_id
                next_id += 1
            self._session.execute(text(
                "INSERT INTO dashboard_widgets(id,user_id,position,chart_id,config_json,created_at,updated_at) "
                "VALUES(:id,:user_id,:position,:chart_id,:config,:created,:updated)"),
                {"id": identifier, "user_id": user_id, "position": position,
                 "chart_id": widget["chart_id"], "config": widget["config_json"],
                 "created": created, "updated": now})
            saved.append({**widget, "id": identifier})
        return saved
