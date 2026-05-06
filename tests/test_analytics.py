from __future__ import annotations

import pandas as pd

from analytics.performance import build_training_snapshot, consistency_score, weekly_mileage


class DummyUser:
    max_hr = 188
    marathon_goal_time = "02:30:00"


class DummyGoal:
    goal_type = "10k_pb"
    target_distance_km = 10.0
    target_time_minutes = 50.0


EMPTY_ACTIVITIES = pd.DataFrame(
    columns=[
        "date",
        "type",
        "distance",
        "duration",
        "pace",
        "avg_hr",
        "aerobic_effect",
        "anaerobic_effect",
    ]
)
EMPTY_HEALTH = pd.DataFrame(
    columns=[
        "date",
        "sleep_duration",
        "sleep_score",
        "resting_hr",
        "hrv",
        "stress",
        "body_battery",
        "recovery_time",
        "vo2max",
    ]
)


def test_weekly_mileage_uses_latest_activity_as_reference_day() -> None:
    activities = pd.DataFrame(
        [
            {"date": "2026-01-01", "type": "running", "distance": 10.0, "duration": 50.0},
            {"date": "2026-01-03", "type": "cycling", "distance": 50.0, "duration": 120.0},
            {"date": "2026-01-07", "type": "trail_running", "distance": 8.0, "duration": 48.0},
            {"date": "2025-12-01", "type": "running", "distance": 20.0, "duration": 110.0},
        ]
    )

    mileage = weekly_mileage(activities)

    assert mileage["7d"] == 18.0
    assert mileage["28d"] == 18.0
    assert not mileage["weekly_series"].empty


def test_consistency_score_counts_unique_recent_running_days() -> None:
    activities = pd.DataFrame(
        [
            {"date": "2026-01-01", "type": "running", "distance": 5.0, "duration": 30.0},
            {"date": "2026-01-01", "type": "running", "distance": 4.0, "duration": 25.0},
            {"date": "2026-01-03", "type": "treadmill_running", "distance": 6.0, "duration": 36.0},
        ]
    )

    score = consistency_score(activities)

    assert score["active_days"] == 2
    assert score["score"] > 0


def test_training_snapshot_uses_active_goal_target_instead_of_legacy_marathon_goal() -> None:
    snapshot = build_training_snapshot(
        DummyUser(),
        EMPTY_ACTIVITIES,
        EMPTY_HEALTH,
        DummyGoal(),
    )

    projection = snapshot["active_goal_projection"]

    assert snapshot["goal_pace"] == 5.0
    assert projection["race_distance_km"] == 10.0
    assert projection["target_time_minutes"] == 50.0
    assert projection["predicted_time_minutes"] == 54.0
    assert projection["gap_minutes"] == 4.0
