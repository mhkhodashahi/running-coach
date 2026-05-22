from __future__ import annotations

from datetime import datetime

import pandas as pd

from services.coaching_prompts import build_calendar_context, build_decision_prompt, build_telegram_prompt


class DummyGoal:
    name = "Berlin Marathon"
    goal_type = "marathon_pb"
    target_distance_km = 42.195
    target_time_minutes = 240
    target_date = None
    priority = "A"
    notes = ""


class DummyUser:
    name = "Mohammad"


def test_telegram_prompt_requires_specific_training_and_recovery_data() -> None:
    system_prompt, user_prompt = build_telegram_prompt(
        user=DummyUser(),
        goal=DummyGoal(),
        decision_payload={
            "summary": "Recovery should drive today's plan.",
            "yesterday_assessment": "Latest session: running for 10.0 km in 50 min.",
            "tomorrow_recommendation": "Run easy.",
            "weekly_outlook": "Hold mileage steady.",
            "goal_alignment": "Marathon projection is behind target.",
            "risk_level": "moderate",
            "confidence": 62,
            "priority": "Protect recovery.",
            "evidence": ["Sleep score 66", "Body battery 42", "7-day mileage 45.0 km", "Recovery time 28 h"],
            "snapshot_summary": {
                "recovery": {
                    "sleep_score": 66,
                    "sleep_duration": 6.5,
                    "body_battery": 42,
                    "hrv": 38,
                    "resting_hr": 54,
                    "recovery_time": 28,
                },
                "weekly_mileage": {"7d": 45.0, "28d": 160.0},
                "readiness": {"score": 58, "label": "building"},
            },
        },
    )

    assert "latest activity details" in system_prompt
    assert "sleep/recovery" in system_prompt
    assert "body battery" in system_prompt
    assert "4 to 8 concrete metrics" in system_prompt
    assert "Sleep score 66" in user_prompt


def test_decision_prompt_uses_elite_coach_context_and_custom_zones() -> None:
    system_prompt, _ = build_decision_prompt(
        decision_type="daily",
        user=DummyUser(),
        goal=DummyGoal(),
        snapshot={},
        activities_df=pd.DataFrame(),
        prior_decisions=[],
        athlete_note="",
        rules=[],
    )

    assert "elite endurance running coach" in system_prompt
    assert "Zone 2 Easy/Aerobic: 110-128 bpm" in system_prompt
    assert "ego pacing" in system_prompt
    assert "brutally honest conclusion" in system_prompt
    assert "Map the requested eight-part coaching analysis" in system_prompt


def test_telegram_prompt_uses_elite_coach_style() -> None:
    system_prompt, _ = build_telegram_prompt(
        user=DummyUser(),
        goal=DummyGoal(),
        decision_payload={"summary": "Controlled aerobic day."},
    )

    assert "elite endurance running coach" in system_prompt
    assert "Zone 4 Threshold: 147-165 bpm" in system_prompt
    assert "brutally honest conclusion" in system_prompt


def test_decision_prompt_sends_all_activities_from_latest_day() -> None:
    activities = pd.DataFrame(
        [
            {
                "date": "2026-04-28 08:00:00",
                "type": "running",
                "distance": 8.0,
                "duration": 44.0,
                "pace": 5.5,
                "avg_hr": 142,
                "max_hr": 165,
                "cadence": 170,
                "elevation": 50,
                "training_effect": 2.5,
                "aerobic_effect": 2.4,
                "anaerobic_effect": 0.2,
                "notes": "",
            },
            {
                "date": "2026-04-30 07:30:00",
                "type": "running",
                "distance": 10.0,
                "duration": 50.0,
                "pace": 5.0,
                "avg_hr": 150,
                "max_hr": 172,
                "cadence": 176,
                "elevation": 80,
                "training_effect": 3.1,
                "aerobic_effect": 3.0,
                "anaerobic_effect": 0.4,
                "notes": "steady run",
            },
            {
                "date": "2026-04-30 18:00:00",
                "type": "strength_training",
                "distance": 0.0,
                "duration": 35.0,
                "pace": None,
                "avg_hr": 105,
                "max_hr": 132,
                "cadence": None,
                "elevation": 0,
                "training_effect": 1.0,
                "aerobic_effect": 1.0,
                "anaerobic_effect": 0.0,
                "notes": "core",
            },
        ]
    )

    _, user_prompt = build_decision_prompt(
        decision_type="daily",
        user=DummyUser(),
        goal=DummyGoal(),
        snapshot={},
        activities_df=activities,
        prior_decisions=[],
        athlete_note="",
        rules=[],
    )

    assert "<latest_day_activities>" in user_prompt
    assert "strength_training" in user_prompt
    assert "running_distance_km\": 10.0" in user_prompt
    assert "activity_count\": 2" in user_prompt
    assert "2026-04-28" not in user_prompt
    assert "<calendar_context>" in user_prompt
    assert "current_local_human" in user_prompt


def test_calendar_context_marks_latest_activity_today() -> None:
    today = datetime.now().astimezone().date()
    context = build_calendar_context(
        pd.DataFrame(
            [
                {
                    "date": today.isoformat(),
                    "type": "running",
                    "distance": 8.0,
                    "duration": 44.0,
                }
            ]
        )
    )

    assert context["current_local_date"] == today.isoformat()
    assert context["latest_activity_day"]["is_today"] is True
    assert context["latest_activity_day"]["days_ago"] == 0
    assert today.strftime("%A") in context["current_local_human"]
