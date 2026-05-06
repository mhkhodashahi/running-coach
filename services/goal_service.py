"""Goal helpers for coaching workflows."""

from __future__ import annotations

from analytics.performance import GOAL_RACE_DISTANCES
from db import repository

GOAL_LABELS = {
    "5k_pb": "5K PB",
    "10k_pb": "10K PB",
    "half_pb": "Half Marathon PB",
    "marathon_pb": "Marathon PB",
}


class GoalService:
    """Resolve the athlete's active goal and goal metadata."""

    def ensure_active_goal(self, session, user):
        goal = repository.get_active_goal(session, user.id)
        if goal is not None:
            return goal
        return repository.get_or_create_default_goal(session, user)

    @staticmethod
    def supported_goal_types() -> list[tuple[str, str, float]]:
        return [
            (goal_type, GOAL_LABELS.get(goal_type, goal_type), distance)
            for goal_type, distance in GOAL_RACE_DISTANCES.items()
        ]

    @staticmethod
    def label_for(goal_type: str) -> str:
        return GOAL_LABELS.get(goal_type, goal_type.replace("_", " ").title())
