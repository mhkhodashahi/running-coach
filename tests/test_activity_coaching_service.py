from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db import repository
from db.models import Base
from services.activity_coaching_service import (
    ActivityCoachingService,
    build_activity_coaching_context,
    build_activity_coaching_prompt,
    can_generate_activity_coach_opinion,
    supports_activity_coach_opinion,
)


def test_activity_coach_opinion_is_only_for_runs() -> None:
    assert supports_activity_coach_opinion("running")
    assert supports_activity_coach_opinion("trail_running")
    assert supports_activity_coach_opinion("treadmill_running")
    assert not supports_activity_coach_opinion("cycling")
    assert not supports_activity_coach_opinion("strength_training")


def test_garmin_run_without_details_is_not_ready_for_one_time_opinion() -> None:
    activity = SimpleNamespace(type="running", external_id="garmin-123", notes=None)

    ready = can_generate_activity_coach_opinion(
        activity=activity,
        track_points=pd.DataFrame(),
        laps=pd.DataFrame(),
    )

    assert ready.allowed is False
    assert "detail data" in ready.reason


def test_run_with_stream_data_is_ready_for_one_time_opinion() -> None:
    activity = SimpleNamespace(type="running", external_id="garmin-123", notes=None)

    ready = can_generate_activity_coach_opinion(
        activity=activity,
        track_points=pd.DataFrame([{"heart_rate": 124, "pace": 6.1}]),
        laps=pd.DataFrame(),
    )

    assert ready.allowed is True


def test_readiness_accepts_activity_dataframe_row() -> None:
    activity = pd.Series({"type": "running", "external_id": "garmin-123", "notes": None})

    ready = can_generate_activity_coach_opinion(
        activity=activity,
        track_points=pd.DataFrame(),
        laps=pd.DataFrame(),
    )

    assert ready.allowed is False


class FailingLLM:
    def generate_json(self, *args, **kwargs):
        raise AssertionError("LLM should not be called when insight already exists")


def test_activity_coach_opinion_is_loaded_from_db_without_regeneration() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)

    with session_factory() as session:
        user = repository.get_or_create_default_user(session, 1)
        repository.bulk_upsert_activities(
            session,
            [
                {
                    "user_id": user.id,
                    "external_id": "garmin-1",
                    "date": date(2026, 5, 22),
                    "type": "running",
                    "distance": 8.0,
                    "duration": 48.0,
                }
            ],
        )
        activity_id = repository.activity_ids_by_external_id(session, user.id, ["garmin-1"])["garmin-1"]
        repository.upsert_activity_coaching_insight(
            session,
            user_id=user.id,
            activity_id=activity_id,
            summary="Stored assessment",
            payload_json='{"overall_assessment": "Stored assessment"}',
            prompt_context_json="{}",
            model_provider="ollama",
            model_name="test-model",
        )

        result = ActivityCoachingService(llm_client=FailingLLM()).generate(session, user=user, activity_id=activity_id)

    assert result["overall_assessment"] == "Stored assessment"


def test_activity_coaching_prompt_uses_profile_and_required_analysis_categories() -> None:
    user = SimpleNamespace(
        name="Mohammad",
        age=39,
        gender="male",
        weight=89.0,
        height=178.0,
        max_hr=184,
        training_days_per_week=5,
        injury_notes="None",
    )
    goal = SimpleNamespace(
        name="10K PB",
        goal_type="10k_pb",
        target_distance_km=10.0,
        target_time_minutes=48.0,
        target_date=None,
    )
    activity = SimpleNamespace(
        id=10,
        date=date(2026, 5, 22),
        type="running",
        distance=8.0,
        duration=48.0,
        pace=6.0,
        avg_hr=132,
        max_hr=154,
        cadence=170,
        elevation=60,
        training_effect=2.6,
        aerobic_effect=2.5,
        anaerobic_effect=0.1,
        notes="Easy run",
    )
    activities = pd.DataFrame(
        [
            {"id": 1, "date": "2026-05-10", "type": "running", "distance": 7.0, "pace": 6.2, "avg_hr": 134},
            {"id": 10, "date": "2026-05-22", "type": "running", "distance": 8.0, "pace": 6.0, "avg_hr": 132},
        ]
    )
    health = pd.DataFrame(
        [
            {
                "date": "2026-05-22",
                "sleep_score": 76,
                "resting_hr": 47,
                "hrv": 42,
                "body_battery": 71,
                "recovery_time": 8,
            }
        ]
    )
    track_points = pd.DataFrame(
        [
            {"point_index": 0, "elapsed_seconds": 0, "distance_km": 0.0, "pace": 6.2, "heart_rate": 118, "cadence": 168},
            {"point_index": 1, "elapsed_seconds": 1200, "distance_km": 4.0, "pace": 6.0, "heart_rate": 126, "cadence": 170},
            {"point_index": 2, "elapsed_seconds": 2400, "distance_km": 8.0, "pace": 5.8, "heart_rate": 142, "cadence": 172},
        ]
    )

    context = build_activity_coaching_context(
        user=user,
        goal=goal,
        activity=activity,
        activities_df=activities,
        health_df=health,
        track_points=track_points,
        laps=pd.DataFrame(),
        snapshot={"readiness": {"score": 72}, "weekly_mileage": {"7d": 32.0}},
    )
    system_prompt, user_prompt = build_activity_coaching_prompt(
        context,
        running_memory="# Coach Running Memory\n- Easy days stay easy.",
    )

    assert "honest feedback, strengths, mistakes, pacing analysis" in system_prompt
    assert "aerobic_efficiency_analysis" in system_prompt
    assert "mental_performance_insights" in system_prompt
    assert "Use the athlete_profile values" in system_prompt
    assert "# Context Engineering" in system_prompt
    assert "context_engineering.analysis_frame" in system_prompt
    assert '"age": 39' in user_prompt
    assert '"weight_kg": 89.0' in user_prompt
    assert '"pace": "6:00"' in user_prompt
    assert '"median_pace": "6:12"' in user_prompt
    assert "pace_min_per_km" not in user_prompt
    assert '"context_engineering"' in user_prompt
    assert '"likely_workout_purpose"' in user_prompt
    assert '"key_questions"' in user_prompt
    assert "Zone 2 Easy/Aerobic" in user_prompt
    assert "custom_zone_distribution" in user_prompt
    assert "<running_memory>" in user_prompt
    assert "Easy days stay easy." in user_prompt
