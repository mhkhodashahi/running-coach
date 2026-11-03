from __future__ import annotations

from datetime import date
from io import StringIO

import pandas as pd
import pytest
from pydantic import ValidationError

from services.garmin_client import CSVGarminClient, GarminAPIClient
from services.garmin_models import validate_laps, validate_track_points
from services.garmin_normalization import (
    _extract_recovery_time_hours,
    extract_activity_exercise_sets,
    extract_activity_track_points,
)
from services.route_geometry import downsample_route, encode_polyline, route_heading_degrees


def test_strength_sets_preserve_intervals_without_inventing_exercises() -> None:
    payload = {"exerciseSets": [
        {"setType": "ACTIVE", "startTime": "2026-10-23 09:00:00", "duration": 32,
         "repetitionCount": 8, "weight": 0,
         "exercises": [{"category": "BENCH_PRESS", "name": None, "probability": .6},
                       {"category": "PUSH_UP", "name": None, "probability": .3}]},
        {"setType": "REST", "duration": 65, "repetitionCount": None, "exercises": []},
    ]}
    rows = extract_activity_exercise_sets(payload)
    assert len(rows) == 2
    assert rows[0]["set_type"] == "ACTIVE"
    assert rows[0]["repetition_count"] == 8
    assert rows[0]["weight_grams"] == 0
    assert '"BENCH_PRESS"' in rows[0]["exercises_json"]
    assert rows[1]["set_type"] == "REST"


def test_strength_details_fetch_only_for_gym_and_preserve_failure() -> None:
    class Fake(GarminAPIClient):
        def __init__(self, fail: bool = False) -> None:
            self.fail = fail

        def _get_client(self):
            return object()

        def _call_api(self, request, *, default, context, suppress_errors):
            if context.startswith("activity exercise sets"):
                return None if self.fail else {"exerciseSets": [{"setType": "ACTIVE", "duration": 30}]}
            return default

    rows = [{"external_id": "1", "type": "strength_training", "date": date(2026, 10, 23)},
            {"external_id": "2", "type": "running", "date": date(2026, 10, 23)}]
    assert len(Fake().sync_activity_details(1, rows)["1"]["exercise_sets"]) == 1
    assert "2" not in Fake().sync_activity_details(1, rows)
    assert "1" not in Fake(fail=True).sync_activity_details(1, rows)


def test_validate_track_points_accepts_normalized_gps_rows() -> None:
    rows = validate_track_points(
        [
            {
                "point_index": 0,
                "timestamp": None,
                "elapsed_seconds": 12,
                "distance_km": 0.05,
                "latitude": 52.52,
                "longitude": 13.405,
                "elevation": 38,
                "pace": 5.2,
                "speed": 3.2,
                "heart_rate": 142,
                "cadence": 168,
            }
        ]
    )

    assert rows[0]["point_index"] == 0
    assert rows[0]["latitude"] == 52.52
    assert rows[0]["pace"] == 5.2


def test_csv_garmin_client_preserves_activity_name() -> None:
    rows = CSVGarminClient().load_activities(
        StringIO(
            "activityId,activityName,startTimeLocal,activityType,distance,duration\n"
            "123,Morning Tempo,2026-05-22 07:00:00,running,10000,3300\n"
        ),
        user_id=1,
    )

    assert rows[0]["activity_name"] == "Morning Tempo"


def test_live_garmin_client_preserves_activity_name() -> None:
    class FakeGarminAPIClient(GarminAPIClient):
        def __init__(self) -> None:
            pass

        def _get_client(self):
            return object()

        def _call_api(self, request, *, default, context, suppress_errors):
            if context == "activities":
                return [
                    {
                        "activityId": 123,
                        "activityName": "Lunch Threshold Run",
                        "startTimeLocal": "2026-05-22 12:00:00",
                        "activityType": {"typeKey": "running"},
                        "distance": 10000,
                        "duration": 3300,
                    }
                ]
            return default

    result = FakeGarminAPIClient().sync_recent_data(user_id=1, days=1, health_days=0)

    assert result.health_rows == []
    assert result.activity_rows[0]["activity_name"] == "Lunch Threshold Run"


def test_live_health_fetch_distinguishes_failed_and_empty_sleep() -> None:
    class FakeGarmin:
        sleep_fails = True

        def get_activities_by_date(self, *_args):
            return []

        def get_stats(self, _day):
            return {"restingHeartRate": 53}

        def get_sleep_data(self, _day):
            if self.sleep_fails:
                raise RuntimeError("temporary sleep endpoint failure")
            return {}

        def get_body_battery(self, *_args):
            return []

        def get_hrv_data(self, _day):
            return {"hrvSummary": {"lastNightAvg": 64}}

        def get_max_metrics(self, _day):
            return {}

        def get_morning_training_readiness(self, _day):
            return {}

        def get_training_readiness(self, _day):
            return {}

        def get_training_status(self, _day):
            return {}

    class FakeGarminAPIClient(GarminAPIClient):
        def __init__(self):
            self.fake = FakeGarmin()

        def _get_client(self):
            return self.fake

    client = FakeGarminAPIClient()
    failed = client.sync_recent_data(user_id=1, days=1, health_days=1)
    assert failed.night_details_complete is False
    assert "sleep_duration" not in failed.health_rows[0]
    assert failed.health_rows[0]["hrv"] == 64

    client.fake.sleep_fails = False
    empty = client.sync_recent_data(user_id=1, days=1, health_days=1)
    assert empty.night_details_complete is True
    assert empty.health_rows[0]["sleep_duration"] is None


def test_recovery_time_ignores_generic_training_readiness_value() -> None:
    recovery_time = _extract_recovery_time_hours(
        {"value": 61, "qualifierKey": "MODERATE"},
        {"trainingStatus": "productive"},
    )

    assert recovery_time is None


def test_recovery_time_uses_named_recovery_time_fields() -> None:
    recovery_time = _extract_recovery_time_hours(
        {"value": 61},
        {"recoveryTime": 12 * 60 * 60},
    )

    assert recovery_time == 12.0


def test_validate_track_points_converts_garmin_seconds_per_100m_pace() -> None:
    rows = validate_track_points(
        [
            {
                "point_index": 0,
                "pace": 74.405,
            }
        ]
    )

    assert rows[0]["pace"] == 12.401


def test_validate_track_points_converts_garmin_seconds_per_km_pace() -> None:
    rows = validate_track_points(
        [
            {
                "point_index": 0,
                "pace": 315,
            }
        ]
    )

    assert rows[0]["pace"] == 5.25


def test_validate_track_points_prefers_speed_when_raw_pace_is_ambiguous() -> None:
    rows = validate_track_points(
        [
            {
                "point_index": 0,
                "pace": 315,
                "speed": 3.0,
            }
        ]
    )

    assert rows[0]["pace"] == 5.556


def test_extract_activity_track_points_normalizes_direct_pace() -> None:
    rows = extract_activity_track_points(
        {
            "activityDetailMetrics": [
                {
                    "directLatitude": 52.52,
                    "directLongitude": 13.405,
                    "sumElapsedDuration": 120,
                    "sumDistance": 250,
                    "directPace": 74.405,
                }
            ]
        }
    )

    assert rows[0]["pace"] == 12.401


def test_validate_track_points_rejects_bad_coordinates() -> None:
    with pytest.raises(ValidationError):
        validate_track_points(
            [
                {
                    "point_index": 0,
                    "latitude": 120,
                    "longitude": 13.405,
                }
            ]
        )


def test_validate_laps_cleans_lap_type() -> None:
    rows = validate_laps(
        [
            {
                "lap_index": 1,
                "lap_type": " LAP ",
                "duration": 300,
                "distance": 1,
                "pace": 5,
                "avg_hr": 150,
            }
        ]
    )

    assert rows[0]["lap_type"] == "lap"


def test_route_heading_degrees_for_eastbound_route() -> None:
    heading = route_heading_degrees([{"lat": 52.52, "lng": 13.40}, {"lat": 52.52, "lng": 13.41}])

    assert 85 <= heading <= 95


def test_downsample_route_preserves_last_point() -> None:
    route = pd.DataFrame(
        {
            "latitude": [52.0 + index * 0.001 for index in range(20)],
            "longitude": [13.0 + index * 0.001 for index in range(20)],
        }
    )

    sampled = downsample_route(route, max_points=6)

    assert len(sampled) <= 8
    assert sampled.iloc[-1]["latitude"] == route.iloc[-1]["latitude"]


def test_encode_polyline_matches_google_example() -> None:
    encoded = encode_polyline(
        [
            {"lat": 38.5, "lng": -120.2},
            {"lat": 40.7, "lng": -120.95},
            {"lat": 43.252, "lng": -126.453},
        ]
    )

    assert encoded == "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
