from __future__ import annotations

from io import StringIO

import pandas as pd
import pytest
from pydantic import ValidationError

from services.garmin_client import CSVGarminClient, GarminAPIClient, extract_activity_track_points
from services.garmin_models import validate_laps, validate_track_points
from ui.google_maps import downsample_route, encode_polyline, route_heading_degrees


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

    activity_rows, health_rows = FakeGarminAPIClient().sync_recent_data(user_id=1, days=1, health_days=0)

    assert health_rows == []
    assert activity_rows[0]["activity_name"] == "Lunch Threshold Run"


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
