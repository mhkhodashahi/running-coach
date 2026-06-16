from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

from services.training_context_service import AppBootstrapService, TrainingBundle


@contextmanager
def fake_session_scope():
    yield object()


class FakeImportService:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def seed_demo_data(self, session: Any, user_id: int) -> None:
        self.calls.append(f"seed_demo:{user_id}")


class FakePredictionService:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def store_for_latest_runs(self, session: Any, *, user: Any) -> None:
        self.calls.append(f"store_predictions:{user.id}")


class FakeRepository:
    def __init__(
        self,
        calls: list[str],
        *,
        activities_count: int = 1,
        health_metrics_count: int = 1,
        prediction_snapshots: pd.DataFrame | None = None,
    ) -> None:
        self.calls = calls
        self._activities_count = activities_count
        self._health_metrics_count = health_metrics_count
        self._prediction_snapshots = prediction_snapshots if prediction_snapshots is not None else pd.DataFrame([{"id": 1}])
        self.user = SimpleNamespace(id=7, name="Test Athlete")
        self.active_goal = SimpleNamespace(id=3)

    def get_or_create_default_user(self, session: Any, user_id: int) -> Any:
        self.calls.append(f"get_user:{user_id}")
        return self.user

    def activities_count(self, session: Any, user_id: int) -> int:
        self.calls.append(f"activities_count:{user_id}")
        return self._activities_count

    def health_metrics_count(self, session: Any, user_id: int) -> int:
        self.calls.append(f"health_metrics_count:{user_id}")
        return self._health_metrics_count

    def prediction_snapshots_dataframe(self, session: Any, user_id: int) -> pd.DataFrame:
        self.calls.append(f"prediction_snapshots:{user_id}")
        return self._prediction_snapshots

    def get_or_create_default_goal(self, session: Any, user: Any) -> Any:
        self.calls.append(f"ensure_goal:{user.id}")
        return self.active_goal

    def activities_dataframe(self, session: Any, user_id: int) -> pd.DataFrame:
        return pd.DataFrame([{"id": 1, "date": "2026-01-01", "distance": 5.0}])

    def health_metrics_dataframe(self, session: Any, user_id: int) -> pd.DataFrame:
        return pd.DataFrame([{"date": "2026-01-01", "sleep_score": 80}])

    def llm_memory_dataframe(self, session: Any, user_id: int) -> pd.DataFrame:
        return pd.DataFrame()

    def goals_dataframe(self, session: Any, user_id: int) -> pd.DataFrame:
        return pd.DataFrame([{"id": 3, "is_active": True}])

    def coaching_decisions_dataframe(self, session: Any, user_id: int) -> pd.DataFrame:
        return pd.DataFrame()

    def email_deliveries_dataframe(self, session: Any, user_id: int) -> pd.DataFrame:
        return pd.DataFrame()

    def get_active_goal(self, session: Any, user_id: int) -> Any:
        return self.active_goal


def test_app_bootstrap_service_initializes_local_state_in_order() -> None:
    calls: list[str] = []
    service = AppBootstrapService(
        settings=SimpleNamespace(default_user_id=7),
        repository_module=FakeRepository(calls, activities_count=0, prediction_snapshots=pd.DataFrame()),
        import_service=FakeImportService(calls),
        prediction_service=FakePredictionService(calls),
        session_scope_factory=fake_session_scope,
        init_database=lambda: calls.append("init_db"),
    )

    user = service.initialize_default_user()

    assert user.id == 7
    assert calls == [
        "init_db",
        "get_user:7",
        "activities_count:7",
        "seed_demo:7",
        "prediction_snapshots:7",
        "store_predictions:7",
    ]


def test_app_bootstrap_service_loads_training_bundle_through_service_interface() -> None:
    calls: list[str] = []

    def build_snapshot(user: Any, activities: pd.DataFrame, health: pd.DataFrame, active_goal: Any) -> dict[str, Any]:
        return {
            "user_id": user.id,
            "activity_rows": len(activities),
            "health_rows": len(health),
            "goal_id": active_goal.id,
        }

    service = AppBootstrapService(
        settings=SimpleNamespace(default_user_id=7),
        repository_module=FakeRepository(calls),
        import_service=FakeImportService(calls),
        prediction_service=FakePredictionService(calls),
        session_scope_factory=fake_session_scope,
        init_database=lambda: calls.append("init_db"),
        snapshot_builder=build_snapshot,
    )

    bundle = service.load_training_bundle()

    assert isinstance(bundle, TrainingBundle)
    assert bundle.user.id == 7
    assert len(bundle.activities) == 1
    assert len(bundle.health_metrics) == 1
    assert bundle.snapshot == {"user_id": 7, "activity_rows": 1, "health_rows": 1, "goal_id": 3}
    assert "ensure_goal:7" in calls


def test_streamlit_pages_import_training_context_service_not_bootstrap_utility() -> None:
    page_paths = [Path("app/dashboard.py"), *Path("app/pages").glob("*.py")]

    for path in page_paths:
        source = path.read_text()
        assert "from utils.bootstrap import load_training_bundle" not in source


def test_bootstrap_utility_reexports_training_context_service_interface() -> None:
    import services.training_context_service as service_module
    import utils.bootstrap as bootstrap

    assert bootstrap.AppBootstrapService is service_module.AppBootstrapService
    assert bootstrap.TrainingBundle is service_module.TrainingBundle
