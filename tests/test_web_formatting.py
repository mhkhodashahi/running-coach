"""Invented display values for the Today UI."""

from datetime import date

from web.formatting import (
    activity_distance,
    activity_duration,
    delta,
    duration_minutes,
    metric,
    short_date,
    sleep_hours,
    sync_time,
)


def test_short_date_and_local_sync_time():
    assert short_date("2026-10-23") == "Fri 23 Oct"
    assert sync_time("2026-10-24 04:36:00", date(2026, 10, 24), "Europe/Berlin") == "Synced 06:36"
    assert sync_time("2026-10-23 04:36:00", date(2026, 10, 24), "Europe/Berlin") == "Synced Fri 23 Oct, 06:36"
    assert sync_time(None, date(2026, 10, 24), "Europe/Berlin") == "Never synced"


def test_durations_and_baseline_deltas():
    assert sleep_hours(8.2) == "8h 12m"
    assert duration_minutes(78) == "1h 18m"
    assert duration_minutes(30) == "30m"
    assert delta(51, 49, "bpm") == "+2 bpm vs baseline"
    assert delta(61, 64, "ms") == "-3 ms vs baseline"
    assert delta(8.2, 6.9, "sleep") == "+1h 18m vs baseline"
    assert metric(None, "bpm") is None
    assert delta(None, 49, "bpm") is None


def test_stored_activity_units_for_running_walking_and_strength():
    # activities.distance is kilometres; activities.duration is minutes.
    assert activity_distance(4.04) == "4.0 km"
    assert activity_duration(27.27) == "27m"
    assert activity_distance(0.87) == "0.9 km"
    assert activity_duration(9.57) == "10m"
    assert activity_distance(0) is None  # Gym distance does not apply.
    assert activity_duration(28.16) == "28m"
    assert activity_duration(0) is None
    assert activity_duration(92) == "1h 32m"
