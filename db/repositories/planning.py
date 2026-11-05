"""Persistence queries used to build safe training plans."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class PlanningWeekHistory:
    profile: dict[str, Any] | None
    has_running_goal: bool
    recent_activities: list[dict[str, Any]]


@dataclass(frozen=True)
class WorkoutHistory:
    profile: dict[str, Any] | None
    goal: dict[str, Any] | None
    laps: list[dict[str, Any]]
    activities: list[dict[str, Any]]
    previous_workouts: list[str]


class PlanningRepository:
    """Read planning inputs while leaving planning rules in the coach layer."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def habit_activities(
        self, user_id: int, from_date: date, before_date: date
    ) -> list[dict[str, Any]]:
        rows = self._session.execute(text(
            "SELECT date,type,duration FROM activities WHERE user_id=:user_id "
            "AND date>=:from_date AND date<:before_date"),
            {"user_id": user_id, "from_date": from_date.isoformat(),
             "before_date": before_date.isoformat()}).mappings()
        return [dict(row) for row in rows]

    def planned_intents(self, user_id: int, through_date: date) -> dict[int, str | None]:
        rows = self._session.execute(text(
            "SELECT id,planned_intent FROM activities WHERE user_id=:user_id AND date<=:through_date"),
            {"user_id": user_id, "through_date": through_date.isoformat()}).all()
        return {int(activity_id): intent for activity_id, intent in rows}

    def week_history(self, user_id: int, today: date, lookback_days: int) -> PlanningWeekHistory:
        profile = self._session.execute(text("SELECT max_hr,age FROM users WHERE id=:user_id"),
                                        {"user_id": user_id}).mappings().first()
        has_running_goal = self._session.execute(text(
            "SELECT 1 FROM goals WHERE user_id=:user_id AND is_active=1 AND goal_type IN "
            "('running_pb','marathon_pb','5k_pb','10k_pb','half_marathon_pb') LIMIT 1"),
            {"user_id": user_id}).first() is not None
        activities = self._session.execute(text(
            "SELECT type,duration,date FROM activities WHERE user_id=:user_id AND date>=:from_date "
            "AND date<=:through_date AND duration>0"),
            {"user_id": user_id, "from_date": (today - timedelta(days=lookback_days - 1)).isoformat(),
             "through_date": today.isoformat()}).mappings()
        return PlanningWeekHistory(dict(profile) if profile else None, has_running_goal,
                                   [dict(row) for row in activities])

    def workout_history(self, user_id: int, start: date) -> WorkoutHistory:
        from_date = (start - timedelta(weeks=8)).isoformat()
        previous_week = (start - timedelta(days=7)).isoformat()
        profile = self._session.execute(text("SELECT max_hr,age FROM users WHERE id=:user_id"),
                                        {"user_id": user_id}).mappings().first()
        goal = self._session.execute(text(
            "SELECT target_date,target_distance_km,target_time_minutes FROM goals WHERE user_id=:user_id "
            "AND is_active=1 AND goal_type IN ('running_pb','marathon_pb','5k_pb','10k_pb','half_marathon_pb') "
            "ORDER BY id DESC LIMIT 1"), {"user_id": user_id}).mappings().first()
        laps = self._session.execute(text(
            "SELECT a.date,a.type,l.pace,l.avg_hr FROM activity_laps l "
            "JOIN activities a ON a.id=l.activity_id WHERE a.user_id=:user_id "
            "AND a.date>=:from_date AND a.date<:through_date"),
            {"user_id": user_id, "from_date": from_date, "through_date": start.isoformat()}).mappings()
        activities = self._session.execute(text(
            "SELECT date,type,distance,duration FROM activities WHERE user_id=:user_id "
            "AND date>=:from_date AND date<:through_date"),
            {"user_id": user_id, "from_date": from_date, "through_date": start.isoformat()}).mappings()
        workouts = self._session.execute(text(
            "SELECT workout_json FROM plan_sessions WHERE user_id=:user_id AND date>=:from_date "
            "AND date<:through_date AND workout_json IS NOT NULL"),
            {"user_id": user_id, "from_date": previous_week, "through_date": start.isoformat()}).all()
        return WorkoutHistory(dict(profile) if profile else None, dict(goal) if goal else None,
                              [dict(row) for row in laps], [dict(row) for row in activities],
                              [str(row[0]) for row in workouts])

    def logged_activity_types(self, user_id: int, day: date) -> list[str]:
        rows = self._session.execute(text(
            "SELECT type FROM activities WHERE user_id=:user_id AND date=:day"),
            {"user_id": user_id, "day": day.isoformat()}).all()
        return [str(row[0]) for row in rows]

    def athlete_choice(self, user_id: int, day: date) -> str | None:
        row = self._session.execute(text(
            "SELECT payload_json FROM coaching_decisions WHERE user_id=:user_id "
            "AND decision_type='daily_v2' AND decision_date=:day ORDER BY id DESC LIMIT 1"),
            {"user_id": user_id, "day": day.isoformat()}).first()
        return str(row[0]) if row else None

    def has_daily_conflict_proposal(self, user_id: int, version: int, summary: str) -> bool:
        return self._session.execute(text(
            "SELECT 1 FROM coach_proposals WHERE user_id=:user_id AND base_version=:version "
            "AND summary=:summary AND status IN ('pending','applied','partially_applied','dismissed') LIMIT 1"),
            {"user_id": user_id, "version": version, "summary": summary}).first() is not None
