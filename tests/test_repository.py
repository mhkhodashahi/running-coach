from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db import repository
from db.models import Base


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

    assert user.age == 39
    assert user.gender == "male"
    assert user.weight == 89.0
    assert user.max_hr == 184


def test_update_user_profile_saves_max_hr() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)

    with session_factory() as session:
        user = repository.get_or_create_default_user(session, 1)
        repository.update_user_profile(session, user.id, {"max_hr": 194})
        updated = repository.get_or_create_default_user(session, 1)

    assert updated.max_hr == 194


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
