"""Persistence for generated morning briefs and athlete feedback."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


class MorningBriefRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def context_rows(self, user_id: int, day: date) -> dict[str, Any]:
        yesterday = (day - timedelta(days=1)).isoformat()
        previous_start = (day - timedelta(days=28)).isoformat()
        tomorrow = (day + timedelta(days=1)).weekday()
        current = self._session.execute(
            text("SELECT * FROM health_metrics WHERE user_id=:user_id AND date=:date"),
            {"user_id": user_id, "date": day.isoformat()},
        ).mappings().first()
        previous = self._rows("SELECT * FROM health_metrics WHERE user_id=:user_id AND date>=:start "
                              "AND date<:end ORDER BY date DESC LIMIT 28",
                              {"user_id": user_id, "start": previous_start, "end": day.isoformat()})
        sync = self._session.execute(
            text("SELECT last_synced_at FROM garmin_sync_status WHERE user_id=:user_id"),
            {"user_id": user_id},
        ).scalar_one_or_none()
        activities = self._rows("SELECT a.id,a.type,a.date,a.duration,e.rpe FROM activities a "
                                "LEFT JOIN activity_efforts e ON e.activity_id=a.id "
                                "WHERE a.user_id=:user_id AND a.date=:day ORDER BY a.id LIMIT 20",
                                {"user_id": user_id, "day": yesterday})
        today_activities = self._rows("SELECT type FROM activities WHERE user_id=:user_id "
                                      "AND date=:day LIMIT 20",
                                      {"user_id": user_id, "day": day.isoformat()})
        planned = self._session.execute(
            text("SELECT workout_json FROM plan_sessions WHERE user_id=:user_id AND date=:day "
                 "AND status='planned' AND workout_json IS NOT NULL ORDER BY id LIMIT 1"),
            {"user_id": user_id, "day": day.isoformat()},
        ).scalar_one_or_none()
        commitments = self._rows("SELECT sport,kind,weekday FROM fixed_commitments WHERE user_id=:user_id "
                                 "AND active=1 AND weekday IN (:today,:tomorrow) LIMIT 4",
                                 {"user_id": user_id, "today": day.weekday(), "tomorrow": tomorrow})
        sent = self._rows("SELECT b.sections_json FROM morning_briefs b JOIN job_runs j "
                          "ON j.user_id=b.user_id AND j.run_date=b.date AND j.job='morning' AND j.status='sent' "
                          "WHERE b.user_id=:user_id AND b.date<:day ORDER BY b.date DESC LIMIT 3",
                          {"user_id": user_id, "day": day.isoformat()})
        return {"current_health": dict(current) if current else None, "previous_health": previous,
                "last_synced_at": sync, "yesterday_activities": activities,
                "today_activities": today_activities, "planned_workout_json": planned,
                "commitments": commitments, "recent_brief_sections": sent}

    def get(self, user_id: int, day: date) -> dict[str, Any] | None:
        row = self._session.execute(
            text("SELECT sections_json,text,source,model,facts_json FROM morning_briefs "
                 "WHERE user_id=:user_id AND date=:day"),
            {"user_id": user_id, "day": day.isoformat()},
        ).mappings().first()
        return dict(row) if row else None

    def insert_if_absent(self, user_id: int, day: date, text_value: str, sections_json: str,
                         source: str, model: str | None, prompt_version: str, facts_json: str,
                         created_at: datetime) -> None:
        self._session.execute(
            text("INSERT OR IGNORE INTO morning_briefs "
                 "(user_id,date,text,sections_json,source,model,prompt_version,facts_json,created_at) "
                 "VALUES(:user_id,:date,:text,:sections,:source,:model,:prompt,:facts,:created)"),
            {"user_id": user_id, "date": day.isoformat(), "text": text_value, "sections": sections_json,
             "source": source, "model": model, "prompt": prompt_version, "facts": facts_json,
             "created": created_at},
        )

    def save_feedback(self, user_id: int, day: date, feedback: str) -> bool:
        result = self._session.execute(
            text("UPDATE morning_briefs SET feedback=:feedback WHERE user_id=:user_id AND date=:day"),
            {"feedback": feedback, "user_id": user_id, "day": day.isoformat()},
        )
        return result.rowcount == 1

    def _rows(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        return [dict(row) for row in self._session.execute(text(query), params).mappings()]
