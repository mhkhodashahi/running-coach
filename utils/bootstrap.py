"""Application bootstrap helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from analytics.performance import build_training_snapshot
from config import get_settings
from db import repository
from db.session import session_scope
from db.setup import init_db
from services.import_service import GarminImportService


@dataclass
class TrainingBundle:
    """Loaded user, dataframes, and analytics snapshot."""

    user: Any
    activities: pd.DataFrame
    health_metrics: pd.DataFrame
    llm_history: pd.DataFrame
    goals: pd.DataFrame
    coaching_history: pd.DataFrame
    email_history: pd.DataFrame
    snapshot: dict[str, Any]


def bootstrap_app() -> Any:
    """Initialize the app database and seed demo data when empty."""

    settings = get_settings()
    init_db()
    with session_scope() as session:
        user = repository.get_or_create_default_user(session, settings.default_user_id)
        importer = GarminImportService()
        if repository.activities_count(session, user.id) == 0:
            importer.seed_demo_data(session, user.id)
        elif repository.health_metrics_count(session, user.id) == 0:
            importer.seed_demo_data(session, user.id)
        return user


def load_training_bundle() -> TrainingBundle:
    """Load the full app context for the default user."""

    user = bootstrap_app()
    with session_scope() as session:
        user = repository.get_or_create_default_user(session, user.id)
        repository.get_or_create_default_goal(session, user)
        activities = repository.activities_dataframe(session, user.id)
        health = repository.health_metrics_dataframe(session, user.id)
        llm_history = repository.llm_memory_dataframe(session, user.id)
        goals = repository.goals_dataframe(session, user.id)
        coaching_history = repository.coaching_decisions_dataframe(session, user.id)
        email_history = repository.email_deliveries_dataframe(session, user.id)
        active_goal = repository.get_active_goal(session, user.id)
    snapshot = build_training_snapshot(user, activities, health, active_goal)
    return TrainingBundle(
        user=user,
        activities=activities,
        health_metrics=health,
        llm_history=llm_history,
        goals=goals,
        coaching_history=coaching_history,
        email_history=email_history,
        snapshot=snapshot,
    )
