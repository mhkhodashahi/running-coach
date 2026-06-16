"""Application startup and training context loading."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd

from analytics.performance import build_training_snapshot
from config import get_settings
from db import repository
from db.session import session_scope
from db.setup import init_db
from services.import_service import GarminImportService
from services.prediction_snapshot_service import PredictionSnapshotService


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
    prediction_snapshots: pd.DataFrame
    snapshot: dict[str, Any]


class AppBootstrapService:
    """Prepare local app state and load the default athlete training context."""

    def __init__(
        self,
        *,
        settings: Any | None = None,
        repository_module: Any = repository,
        import_service: GarminImportService | None = None,
        prediction_service: PredictionSnapshotService | None = None,
        session_scope_factory: Callable[..., Any] = session_scope,
        init_database: Callable[[], None] = init_db,
        snapshot_builder: Callable[..., dict[str, Any]] = build_training_snapshot,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository_module
        self.import_service = import_service or GarminImportService()
        self.prediction_service = prediction_service or PredictionSnapshotService()
        self.session_scope_factory = session_scope_factory
        self.init_database = init_database
        self.snapshot_builder = snapshot_builder

    def initialize_default_user(self) -> Any:
        """Create schema, default user, demo data, and prediction history when needed."""

        self.init_database()
        with self.session_scope_factory() as session:
            user = self.repository.get_or_create_default_user(session, self.settings.default_user_id)
            self._seed_demo_data_if_needed(session, user.id)
            if self.repository.prediction_snapshots_dataframe(session, user.id).empty:
                self.prediction_service.store_for_latest_runs(session, user=user)
            return user

    def load_training_bundle(self) -> TrainingBundle:
        """Load the full app context for the default user."""

        user = self.initialize_default_user()
        with self.session_scope_factory() as session:
            user = self.repository.get_or_create_default_user(session, user.id)
            self.repository.get_or_create_default_goal(session, user)
            activities = self.repository.activities_dataframe(session, user.id)
            health = self.repository.health_metrics_dataframe(session, user.id)
            llm_history = self.repository.llm_memory_dataframe(session, user.id)
            goals = self.repository.goals_dataframe(session, user.id)
            coaching_history = self.repository.coaching_decisions_dataframe(session, user.id)
            email_history = self.repository.email_deliveries_dataframe(session, user.id)
            prediction_snapshots = self.repository.prediction_snapshots_dataframe(session, user.id)
            active_goal = self.repository.get_active_goal(session, user.id)
        snapshot = self.snapshot_builder(user, activities, health, active_goal)
        return TrainingBundle(
            user=user,
            activities=activities,
            health_metrics=health,
            llm_history=llm_history,
            goals=goals,
            coaching_history=coaching_history,
            email_history=email_history,
            prediction_snapshots=prediction_snapshots,
            snapshot=snapshot,
        )

    def _seed_demo_data_if_needed(self, session: Any, user_id: int) -> None:
        if self.repository.activities_count(session, user_id) == 0:
            self.import_service.seed_demo_data(session, user_id)
        elif self.repository.health_metrics_count(session, user_id) == 0:
            self.import_service.seed_demo_data(session, user_id)


def bootstrap_app() -> Any:
    """Initialize the app database and seed demo data when empty."""

    return AppBootstrapService().initialize_default_user()


def load_training_bundle() -> TrainingBundle:
    """Load the full app context for the default user."""

    return AppBootstrapService().load_training_bundle()
