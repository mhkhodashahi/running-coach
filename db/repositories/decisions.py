"""Persistence for immutable daily coach decisions and separate athlete choices."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


class DailyDecisionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def latest(self, user_id: int, day: date) -> dict[str, Any] | None:
        row = self._session.execute(
            text("SELECT id,payload_json FROM coaching_decisions WHERE user_id=:user_id "
                 "AND decision_type='daily_v2' AND decision_date=:day ORDER BY id DESC LIMIT 1"),
            {"user_id": user_id, "day": day.isoformat()},
        ).mappings().first()
        return dict(row) if row else None

    def inputs(self, user_id: int, day: date, lookback_days: int = 7) -> dict[str, Any]:
        from datetime import timedelta

        start = (day - timedelta(days=lookback_days)).isoformat()
        health = self._rows("SELECT date,sleep_duration,hrv FROM health_metrics "
                            "WHERE user_id=:user_id AND date<=:day ORDER BY date DESC",
                            {"user_id": user_id, "day": day.isoformat()})
        sync = self._session.execute(
            text("SELECT last_synced_at FROM garmin_sync_status WHERE user_id=:user_id"),
            {"user_id": user_id},
        ).scalar_one_or_none()
        activities = self._rows(
            "SELECT a.id,a.date,a.type,a.planned_intent,i.payload_json,e.rpe,"
            "(SELECT MIN(timestamp) FROM activity_track_points t WHERE t.activity_id=a.id) AS first_point "
            "FROM activities a LEFT JOIN activity_coaching_insights i ON i.activity_id=a.id "
            "LEFT JOIN activity_efforts e ON e.activity_id=a.id "
            "WHERE a.user_id=:user_id AND a.date>=:start AND a.date<=:day ORDER BY a.date,a.id",
            {"user_id": user_id, "start": start, "day": day.isoformat()},
        )
        profile = self._one("SELECT max_hr,age FROM users WHERE id=:user_id", {"user_id": user_id})
        fixed = self._rows(
            "SELECT f.sport FROM fixed_commitments f WHERE f.user_id=:user_id "
            "AND f.weekday=:weekday AND f.active=1 AND NOT EXISTS (SELECT 1 FROM plan_sessions p "
            "WHERE p.user_id=f.user_id AND p.fixed_commitment_id=f.id AND p.date=:day AND p.status='skipped')",
            {"user_id": user_id, "weekday": day.weekday(), "day": day.isoformat()},
        )
        planned = self._rows("SELECT sport FROM plan_sessions WHERE user_id=:user_id AND date=:day "
                             "AND sport IN ('football','volleyball') AND status='planned'",
                             {"user_id": user_id, "day": day.isoformat()})
        goal = self._one("SELECT goal_type,target_distance_km FROM goals WHERE user_id=:user_id "
                         "AND is_active=1 LIMIT 1", {"user_id": user_id})
        memories = self._rows("SELECT id,text,rule_json FROM coach_memories WHERE user_id=:user_id "
                              "AND status='active' AND valid_from<=:day "
                              "AND (valid_until IS NULL OR valid_until>=:day) "
                              "ORDER BY created_at DESC LIMIT 30",
                              {"user_id": user_id, "day": day.isoformat()})
        return {"health": health, "last_synced_at": sync, "recent_activities": activities,
                "profile": profile, "fixed_teams": fixed, "planned_teams": planned,
                "active_goal": goal, "memories": memories}

    def week_activity_types(self, user_id: int, start: date, end: date) -> dict[int, str]:
        rows = self._rows("SELECT id,type FROM activities WHERE user_id=:user_id "
                          "AND date>=:start AND date<=:end",
                          {"user_id": user_id, "start": start.isoformat(), "end": end.isoformat()})
        return {int(row["id"]): str(row["type"]) for row in rows}

    def save(self, user_id: int, day: date, summary: str, risk_level: str,
             payload_json: str, created_at: datetime) -> int:
        result = self._session.execute(
            text("INSERT INTO coaching_decisions "
                 "(user_id,goal_id,decision_type,decision_date,summary,risk_level,payload_json,created_at) "
                 "VALUES(:user_id,NULL,'daily_v2',:day,:summary,:risk,:payload,:created_at)"),
            {"user_id": user_id, "day": day.isoformat(), "summary": summary, "risk": risk_level,
             "payload": payload_json, "created_at": created_at},
        )
        return int(result.lastrowid or 0)

    def save_athlete_choice(self, user_id: int, day: date, choice: str) -> dict[str, Any] | None:
        self._session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        row = self.latest(user_id, day)
        if row is None:
            return None
        import json

        payload = json.loads(row["payload_json"])
        payload["athlete_choice"] = choice
        payload["decision"]["athlete_choice"] = choice
        self._session.execute(
            text("UPDATE coaching_decisions SET payload_json=:payload WHERE id=:id"),
            {"payload": json.dumps(payload), "id": row["id"]},
        )
        return payload["decision"]

    def _one(self, query: str, params: dict[str, Any]) -> dict[str, Any] | None:
        row = self._session.execute(text(query), params).mappings().first()
        return dict(row) if row else None

    def _rows(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        return [dict(row) for row in self._session.execute(text(query), params).mappings()]
