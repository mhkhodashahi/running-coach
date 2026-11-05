"""Persistence boundary for activity lists, details, and user actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from db.models import ActivityEffort


@dataclass(frozen=True)
class ActivityDetailData:
    activity: dict[str, Any]
    laps: list[dict[str, Any]]
    exercise_sets: list[dict[str, Any]]
    heart_rate_points: list[dict[str, Any]]
    cadence_range: tuple[float | None, float | None]
    athlete: dict[str, Any] | None
    opinion: dict[str, Any] | None
    calls_today: int
    previous_id: int | None
    next_id: int | None
    first_time: str | None


class ActivityRepository:
    """Own SQL for activity-domain reads and mutations; callers own the session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_rows(self, user_id: int, start: date | None, end: date | None) -> list[dict[str, Any]]:
        rows = self._session.execute(text(
            "SELECT a.*,e.rpe,i.id AS opinion_id FROM activities a "
            "LEFT JOIN activity_efforts e ON e.activity_id=a.id "
            "LEFT JOIN activity_coaching_insights i ON i.activity_id=a.id AND i.user_id=a.user_id "
            "WHERE a.user_id=:user_id AND (:start IS NULL OR a.date>=:start) "
            "AND (:end IS NULL OR a.date<=:end) ORDER BY a.date DESC,a.id DESC"),
            {"user_id": user_id, "start": start.isoformat() if start else None,
             "end": end.isoformat() if end else None}).mappings()
        return [dict(row) for row in rows]

    def ids_for_user(self, user_id: int) -> set[int]:
        rows = self._session.execute(text("SELECT id FROM activities WHERE user_id=:user_id"),
                                     {"user_id": user_id})
        return {int(row[0]) for row in rows}

    def effort_rating(self, activity_id: int) -> ActivityEffort | None:
        return self._session.get(ActivityEffort, activity_id)

    def effort_ratings(self, activity_ids: list[int]) -> dict[int, int]:
        if not activity_ids:
            return {}
        rows = self._session.execute(text(
            "SELECT activity_id,rpe FROM activity_efforts WHERE activity_id IN "
            "(" + ",".join(f":id_{index}" for index in range(len(activity_ids))) + ")"),
            {f"id_{index}": identifier for index, identifier in enumerate(activity_ids)}).all()
        return {int(row[0]): int(row[1]) for row in rows}

    def detail(self, user_id: int, activity_id: int, local_day: date) -> ActivityDetailData | None:
        activity_row = self._session.execute(text(
            "SELECT a.*,e.rpe FROM activities a LEFT JOIN activity_efforts e ON e.activity_id=a.id "
            "WHERE a.id=:activity_id AND a.user_id=:user_id"),
            {"activity_id": activity_id, "user_id": user_id}).mappings().first()
        if activity_row is None:
            return None
        activity = dict(activity_row)
        laps = self._rows("SELECT lap_index,lap_type,distance,duration,pace,avg_hr,avg_cadence "
                           "FROM activity_laps WHERE activity_id=:id ORDER BY lap_index", activity_id)
        exercise_sets = self._rows(
            "SELECT set_index,set_type,duration_seconds,repetition_count,weight_grams,exercises_json "
            "FROM activity_exercise_sets WHERE activity_id=:id ORDER BY set_index", activity_id)
        heart_rate_points = self._rows(
            "SELECT elapsed_seconds,heart_rate FROM activity_track_points "
            "WHERE activity_id=:id AND heart_rate IS NOT NULL ORDER BY point_index", activity_id)
        cadence = self._session.execute(text(
            "SELECT MIN(avg_cadence),MAX(avg_cadence) FROM activity_laps "
            "WHERE activity_id=:id AND distance>=0.9"), {"id": activity_id}).first()
        athlete_row = self._session.execute(text("SELECT max_hr,age FROM users WHERE id=:id"),
                                            {"id": user_id}).mappings().first()
        opinion_row = self._session.execute(text(
            "SELECT * FROM activity_coaching_insights WHERE activity_id=:activity_id AND user_id=:user_id"),
            {"activity_id": activity_id, "user_id": user_id}).mappings().first()
        calls = self._session.execute(text(
            "SELECT COUNT(*) FROM coach_llm_calls WHERE user_id=:user_id AND local_day=:day"),
            {"user_id": user_id, "day": local_day.isoformat()}).scalar_one()
        previous_id = self._adjacent_id(activity, user_id, before=True)
        next_id = self._adjacent_id(activity, user_id, before=False)
        return ActivityDetailData(
            activity=activity, laps=laps, exercise_sets=exercise_sets,
            heart_rate_points=heart_rate_points,
            cadence_range=(cadence[0], cadence[1]) if cadence else (None, None),
            athlete=dict(athlete_row) if athlete_row else None,
            opinion=dict(opinion_row) if opinion_row else None, calls_today=int(calls),
            previous_id=previous_id, next_id=next_id,
            first_time=self._first_time(activity_id, date.fromisoformat(activity["date"])),
        )

    def opinion_source(self, user_id: int, activity_id: int) -> tuple[dict[str, Any] | None,
                                                                      dict[str, Any] | None]:
        activity = self._session.execute(text(
            "SELECT date FROM activities WHERE id=:activity_id AND user_id=:user_id"),
            {"activity_id": activity_id, "user_id": user_id}).mappings().first()
        opinion = self._session.execute(text(
            "SELECT * FROM activity_coaching_insights WHERE activity_id=:activity_id AND user_id=:user_id"),
            {"activity_id": activity_id, "user_id": user_id}).mappings().first()
        return (dict(activity) if activity else None, dict(opinion) if opinion else None)

    def session_summaries(self, user_id: int, activity_ids: list[int]) -> dict[int, dict[str, Any]]:
        if not activity_ids:
            return {}
        placeholders = ",".join(f":id_{index}" for index in range(len(activity_ids)))
        params = {f"id_{index}": identifier for index, identifier in enumerate(activity_ids)}
        params["user_id"] = user_id
        rows = self._session.execute(text(
            f"SELECT id,date,duration FROM activities WHERE user_id=:user_id AND id IN ({placeholders})"),
            params).mappings()
        return {int(row["id"]): dict(row) for row in rows}

    def set_planned_intent(self, user_id: int, activity_id: int, intent: str | None) -> bool:
        result = self._session.execute(text(
            "UPDATE activities SET planned_intent=:intent WHERE id=:activity_id AND user_id=:user_id"),
            {"intent": intent, "activity_id": activity_id, "user_id": user_id})
        return result.rowcount == 1

    def exists(self, user_id: int, activity_id: int) -> bool:
        return self._session.execute(text(
            "SELECT 1 FROM activities WHERE id=:activity_id AND user_id=:user_id"),
            {"activity_id": activity_id, "user_id": user_id}).first() is not None

    def _rows(self, query: str, activity_id: int) -> list[dict[str, Any]]:
        return [dict(row) for row in self._session.execute(text(query), {"id": activity_id}).mappings()]

    def _adjacent_id(self, activity: dict[str, Any], user_id: int, *, before: bool) -> int | None:
        comparator, order = ("<", "DESC") if before else (">", "ASC")
        row = self._session.execute(text(
            f"SELECT id FROM activities WHERE user_id=:user_id AND "
            f"(date {comparator} :day OR (date=:day AND id {comparator} :activity_id)) "
            f"ORDER BY date {order},id {order} LIMIT 1"),
            {"user_id": user_id, "day": activity["date"], "activity_id": activity["id"]}).first()
        return int(row[0]) if row else None

    def _first_time(self, activity_id: int, activity_day: date) -> str | None:
        raw = self._session.execute(text(
            "SELECT MIN(start_time) FROM activity_laps WHERE activity_id=:id"),
            {"id": activity_id}).scalar_one_or_none()
        if raw is None:
            raw = self._session.execute(text(
                "SELECT MIN(timestamp) FROM activity_track_points WHERE activity_id=:id"),
                {"id": activity_id}).scalar_one_or_none()
        if raw is None:
            return None
        from datetime import datetime

        stamp = datetime.fromisoformat(str(raw))
        return stamp.strftime("%H:%M") if stamp.date() == activity_day else None
