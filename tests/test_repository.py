from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from db import repository
from db.models import Base
from services.garmin_client import GarminSyncResult
from services.garmin_normalization import normalize_live_health_row
from services.import_service import GarminImportService


def test_coaching_decisions_dataframe_parses_mixed_created_at_formats() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users(id,running_goal_time) VALUES(1,'03:59:59')"))
        connection.execute(text(
            "INSERT INTO coaching_decisions(user_id,decision_type,decision_date,summary,"
            "risk_level,payload_json,created_at) VALUES"
            "(1,'daily','2026-06-17','test','moderate','{}','2026-06-16T13:54:51.477821'),"
            "(1,'daily','2026-06-16','test','moderate','{}','2026-06-16 13:54:51.477821')"
        ))
    with sessionmaker(bind=engine, future=True)() as session:
        result = repository.coaching_decisions_dataframe(session, 1)
    assert list(result["created_at"]) == [pd.Timestamp("2026-06-16 13:54:51.477821")] * 2
    assert list(result["decision_date"]) == [pd.Timestamp("2026-06-17"), pd.Timestamp("2026-06-16")]
    engine.dispose()


def test_bulk_upsert_activities_updates_existing_external_activity() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)

    with session_factory() as session:
        repository.get_or_create_default_user(session, 1)
        first_count = repository.bulk_upsert_activities(
            session,
            [
                {
                    "user_id": 1,
                    "external_id": "garmin-1",
                    "activity_name": "Morning Tempo",
                    "date": date(2026, 1, 1),
                    "type": "running",
                    "distance": 10.0,
                    "duration": 50.0,
                    "pace": 5.0,
                    "avg_hr": 150,
                }
            ],
        )
        second_count = repository.bulk_upsert_activities(
            session,
            [
                {
                    "user_id": 1,
                    "external_id": "garmin-1",
                    "activity_name": "Updated Morning Tempo",
                    "date": date(2026, 1, 1),
                    "type": "running",
                    "distance": 11.0,
                    "duration": 55.0,
                    "pace": 5.0,
                    "avg_hr": 148,
                }
            ],
        )
        activities = repository.activities_dataframe(session, 1)

    assert first_count == 1
    assert second_count == 0
    assert len(activities) == 1
    assert activities.iloc[0]["distance"] == 11.0
    assert activities.iloc[0]["activity_name"] == "Updated Morning Tempo"


def test_replace_activity_track_points_is_idempotent() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)

    with session_factory() as session:
        repository.get_or_create_default_user(session, 1)
        repository.bulk_upsert_activities(
            session,
            [
                {
                    "user_id": 1,
                    "external_id": "garmin-1",
                    "date": date(2026, 1, 1),
                    "type": "running",
                    "distance": 10.0,
                    "duration": 50.0,
                }
            ],
        )
        activity_id = repository.activity_ids_by_external_id(session, 1, ["garmin-1"])["garmin-1"]
        repository.replace_activity_track_points(
            session,
            activity_id,
            [{"point_index": 0, "latitude": 52.52, "longitude": 13.405}],
        )
        repository.replace_activity_track_points(
            session,
            activity_id,
            [{"point_index": 0, "latitude": 52.53, "longitude": 13.406}],
        )
        points = repository.track_points_dataframe(session, activity_id)

    assert len(points) == 1
    assert points.iloc[0]["latitude"] == 52.53


def test_default_goal_uses_goal_settings_not_legacy_user_running_time() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)

    with session_factory() as session:
        user = repository.get_or_create_default_user(session, 1)
        user.running_goal_time = "02:30:00"
        goal = repository.get_or_create_default_goal(session, user)

    assert goal.target_time_minutes == 240.0
    assert goal.goal_type == "running_pb"
    assert goal.is_active is True


def test_default_user_matches_activity_coach_profile() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)

    with session_factory() as session:
        user = repository.get_or_create_default_user(session, 1)

    assert user.name == "Demo Athlete"
    assert user.age == 35
    assert user.gender == "unspecified"
    assert user.weight == 75.0
    assert user.height == 175.0
    assert user.max_hr == 185


def test_update_user_profile_saves_max_hr() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)

    with session_factory() as session:
        user = repository.get_or_create_default_user(session, 1)
        repository.update_user_profile(session, user.id, {"max_hr": 194})
        updated = repository.get_or_create_default_user(session, 1)

    assert updated.max_hr == 194


def test_garmin_sync_status_is_saved_only_after_success(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)

    class SuccessfulClient:
        def __init__(self, **kwargs):
            pass

        def sync_recent_data(self, **kwargs):
            return GarminSyncResult([], [], True)

    class FailingClient(SuccessfulClient):
        def sync_recent_data(self, **kwargs):
            raise RuntimeError("Garmin unavailable")

    with session_factory.begin() as session:
        repository.get_or_create_default_user(session, 1)
        assert repository.get_last_garmin_sync(session, 1) is None

    monkeypatch.setattr("services.import_service.GarminAPIClient", SuccessfulClient)
    with session_factory.begin() as session:
        GarminImportService().sync_garmin(session, user_id=1)

    with session_factory() as session:
        synced_at = repository.get_last_garmin_sync(session, 1)
        assert synced_at is not None

    monkeypatch.setattr("services.import_service.GarminAPIClient", FailingClient)
    with session_factory() as session:
        with pytest.raises(RuntimeError, match="Garmin unavailable"):
            GarminImportService().sync_garmin(session, user_id=1)
        assert repository.get_last_garmin_sync(session, 1) == synced_at


def test_partial_garmin_health_sync_preserves_existing_values(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)
    day = date(2026, 10, 26)
    state = {"mode": "failed"}

    class PartialClient:
        def __init__(self, **_kwargs):
            pass

        def sync_recent_data(self, **_kwargs):
            mode = state["mode"]
            row = normalize_live_health_row(
                user_id=1, current_day=day, stats={"restingHeartRate": 53},
                sleep=({"dailySleepDTO": {"sleepTimeSeconds": 28800},
                        "sleepScores": {"overall": {"value": 84}}} if mode == "data" else {}),
                body_battery=[],
                hrv={"hrvSummary": {"lastNightAvg": 64}} if mode == "data" else {},
                max_metrics={},
                training_readiness={}, training_status={},
                failed_sources=frozenset({"sleep", "hrv"}) if mode == "failed" else frozenset(),
                include_empty=True,
            )
            return GarminSyncResult([], [row], mode != "failed")

    with session_factory.begin() as session:
        repository.get_or_create_default_user(session, 1)
        repository.bulk_upsert_health_metrics(session, [{
            "user_id": 1, "date": day, "sleep_duration": 7.5,
            "sleep_score": 82, "sleep_deep_min": 65,
            "hrv": 62, "hrv_weekly_avg": 61, "resting_hr": 55,
        }])

    monkeypatch.setattr("services.import_service.GarminAPIClient", PartialClient)
    with session_factory.begin() as session:
        GarminImportService().sync_garmin(session, 1, include_activities=False)

    with session_factory() as session:
        metric = session.execute(text(
            "SELECT sleep_duration,sleep_score,sleep_deep_min,hrv,hrv_weekly_avg,resting_hr "
            "FROM health_metrics WHERE user_id=1 AND date=:day"
        ), {"day": day.isoformat()}).one()
        assert tuple(metric) == (7.5, 82, 65, 62, 61, 53)
        assert session.execute(text(
            "SELECT night_details_backfilled_at FROM garmin_sync_status WHERE user_id=1"
        )).scalar_one() is None

    state["mode"] = "empty"
    with session_factory.begin() as session:
        GarminImportService().sync_garmin(session, 1, include_activities=False)

    with session_factory() as session:
        metric = session.execute(text(
            "SELECT sleep_duration,sleep_score,sleep_deep_min,hrv,hrv_weekly_avg,resting_hr "
            "FROM health_metrics WHERE user_id=1 AND date=:day"
        ), {"day": day.isoformat()}).one()
        assert tuple(metric) == (None, None, None, None, None, 53)
        assert session.execute(text(
            "SELECT night_details_backfilled_at FROM garmin_sync_status WHERE user_id=1"
        )).scalar_one() is not None

    state["mode"] = "data"
    with session_factory.begin() as session:
        GarminImportService().sync_garmin(session, 1, include_activities=False)
    with session_factory() as session:
        metric = session.execute(text(
            "SELECT sleep_duration,sleep_score,hrv FROM health_metrics WHERE user_id=1 AND date=:day"
        ), {"day": day.isoformat()}).one()
        assert tuple(metric) == (8.0, 84, 64)
    engine.dispose()


def test_default_health_upsert_can_clear_a_value() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True)() as session:
        repository.get_or_create_default_user(session, 1)
        row = {"user_id": 1, "date": date(2026, 10, 26), "sleep_duration": 7.5}
        repository.bulk_upsert_health_metrics(session, [row])
        repository.bulk_upsert_health_metrics(session, [{**row, "sleep_duration": None}])
        assert session.execute(text(
            "SELECT sleep_duration FROM health_metrics WHERE user_id=1"
        )).scalar_one() is None
    engine.dispose()


def test_live_health_upsert_skips_empty_new_days() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True)() as session:
        repository.get_or_create_default_user(session, 1)
        count = repository.bulk_upsert_health_metrics(session, [{
            "user_id": 1, "date": date(2026, 10, 26), "sleep_duration": None,
        }], skip_empty_inserts=True)
        assert count == 0
        assert session.execute(text("SELECT COUNT(*) FROM health_metrics")).scalar_one() == 0
    engine.dispose()


def test_nutrition_entries_can_be_created_listed_and_deleted() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)

    with session_factory() as session:
        repository.get_or_create_default_user(session, 1)
        entry = repository.create_nutrition_entry(
            session,
            1,
            {
                "entry_date": date(2026, 2, 1),
                "meal_type": "breakfast",
                "food_name": "Oats and yogurt",
                "calories": 520,
                "protein_g": 32,
                "carbs_g": 72,
                "fat_g": 11,
                "notes": "Long-run morning.",
            },
        )
        logged = repository.nutrition_entries_dataframe(session, 1)
        repository.delete_nutrition_entry(session, entry.id, 1)
        after_delete = repository.nutrition_entries_dataframe(session, 1)

    assert len(logged) == 1
    assert logged.iloc[0]["food_name"] == "Oats and yogurt"
    assert logged.iloc[0]["calories"] == 520
    assert after_delete.empty
