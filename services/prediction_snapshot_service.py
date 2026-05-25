"""Persist race prediction snapshots after running activities."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from analytics.performance import build_goal_projection
from db import repository
from services.goal_service import GoalService


class PredictionSnapshotService:
    """Create prediction history points tied to activities."""

    def __init__(self) -> None:
        self.goal_service = GoalService()

    def store_for_latest_runs(self, session, *, user: Any, limit: int | None = None) -> int:
        """Store missing/updatable prediction snapshots for recent runs."""

        goal = self.goal_service.ensure_active_goal(session, user)
        activities = repository.activities_dataframe(session, user.id)
        health = repository.health_metrics_dataframe(session, user.id)
        if activities.empty:
            return 0

        runs = activities[activities["type"].fillna("").str.contains("run|trail|treadmill", case=False, na=False)].copy()
        if runs.empty:
            return 0
        runs["date"] = pd.to_datetime(runs["date"])
        runs = runs.sort_values("date")
        if limit is not None:
            runs = runs.tail(limit)

        stored = 0
        all_activities = activities.copy()
        all_activities["date"] = pd.to_datetime(all_activities["date"])
        all_health = health.copy()
        if not all_health.empty:
            all_health["date"] = pd.to_datetime(all_health["date"])

        for row in runs.itertuples():
            activity_day = pd.Timestamp(row.date).normalize()
            activities_to_date = all_activities[all_activities["date"].dt.normalize() <= activity_day]
            health_to_date = all_health[all_health["date"].dt.normalize() <= activity_day] if not all_health.empty else all_health
            projection = build_goal_projection(
                user,
                activities_to_date,
                health_to_date,
                getattr(goal, "goal_type", "running_pb"),
                float(getattr(goal, "target_time_minutes", 240.0)),
                float(getattr(goal, "target_distance_km", 42.195)),
            )
            repository.upsert_prediction_snapshot(
                session,
                user_id=user.id,
                activity_id=int(row.id),
                goal_id=getattr(goal, "id", None),
                prediction_date=activity_day.date(),
                race_distance_km=float(projection["race_distance_km"]),
                predicted_time_minutes=float(projection["predicted_time_minutes"]),
                predicted_pace=float(projection["predicted_pace"]),
                gap_minutes=float(projection["gap_minutes"]),
                confidence=float(projection["confidence"]),
                payload_json=json.dumps(projection, default=str),
            )
            stored += 1
        return stored
