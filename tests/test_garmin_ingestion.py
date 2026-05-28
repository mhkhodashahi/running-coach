from __future__ import annotations

from services.garmin_normalization import extract_activity_track_points, normalize_recovery_time_hours


def test_garmin_normalization_extracts_stream_points_and_recovery_hours() -> None:
    points = extract_activity_track_points(
        {
            "activityDetailMetrics": [
                {
                    "directLatitude": 52.52,
                    "directLongitude": 13.405,
                    "sumElapsedDuration": 120,
                    "sumDistance": 250,
                    "directPace": 315,
                }
            ]
        }
    )

    assert points[0]["latitude"] == 52.52
    assert points[0]["distance_km"] == 0.25
    assert points[0]["pace"] == 5.25
    assert normalize_recovery_time_hours({"recoveryTime": 12 * 60 * 60}) == 12.0
