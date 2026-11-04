"""Invented athlete data for deterministic workout prescription."""

from datetime import date

from coach.workouts import (
    TEMPLATES,
    build_workout,
    goal_phase,
    pace_targets,
    race_paces,
    recent_pace_samples,
    zone_targets,
)


def test_library_templates_and_variants():
    assert set(TEMPLATES) == {"recovery", "easy_base", "long", "tempo", "threshold",
                              "vo2_intervals", "speed", "strength_runners", "upper_core", "mobility"}
    for template in TEMPLATES.values():
        workout = build_workout(template.id, 45, zones={}, paces={})
        assert workout["purpose"] and workout["benefit"]
        assert workout["variants"]["shorter"]["duration_min"] < 45
        assert workout["variants"]["longer"]["duration_min"] > 45
        assert workout["variants"]["shorter"]["steps"]
        assert workout["variants"]["longer"]["steps"]
        assert workout["steps"] and workout["fallback"] and workout["done_right_if"]
        for variant in (workout, workout["variants"]["shorter"], workout["variants"]["longer"]):
            steps = variant["steps"]
            assert sum(step["duration_min"] * step.get("reps", 1) +
                       step.get("recovery_min", 0) * (step.get("reps", 1) - 1)
                       for step in steps) == variant["duration_min"]


def test_targets_use_custom_zones_and_recent_measured_pace():
    zones = zone_targets((("Recovery", 90, 110), ("Easy", 110, 130),
                          ("Steady", 130, 150), ("Hard", 150, 170), ("Max", 170, None)), 200)
    assert zones["Z2"] == (110, 130)
    assert zone_targets((), None) == {}
    paces = pace_targets([(6.0, 120), (6.1, 122), (5.9, 125), (5.0, 160)], zones)
    assert "Z2" in paces and "Z4" not in paces
    workout = build_workout("easy_base", 40, zones=zones, paces=paces, estimated_load=25)
    assert workout["steps"][1]["hr_target"] == "110–130 bpm"
    assert workout["steps"][1]["pace_target"] == paces["Z2"]
    assert workout["estimated_load"] == 25
    assert build_workout("tempo", 48, zones=zones, paces={})["pace_note"]
    gym = build_workout("upper_core", 30, zones={}, paces={})
    assert gym["steps"][1]["rounds"] >= 1
    assert any("reps" in exercise for exercise in gym["steps"][1]["exercises"])
    assert build_workout("long", 38, zones=zones, paces=paces,
                         max_duration_min=38)["variants"]["longer"] is None


def test_race_targets_from_measured_effort_or_goal():
    assert race_paces([(5.0, 25.0), (5.1, 27.0)], (10.0, 52.0))["5K"] == "5:00 /km"
    assert race_paces([], (10.0, 52.0))["10K"] == "5:12 /km"
    assert race_paces([], None) == {}


def test_goal_phase_without_and_with_date():
    start = date(2026, 6, 1)
    assert goal_phase(start, None) == ("maintenance", None)
    assert goal_phase(start, date(2026, 6, 15)) == ("taper", 2)
    assert goal_phase(start, date(2026, 7, 20))[0] == "build"


def test_recent_samples_exclude_future_and_stale_days():
    start = date(2026, 6, 1)
    rows = [(date(2026, 4, 1), 6.0, 120), (date(2026, 5, 31), 5.5, 130),
            (date(2026, 6, 2), 5.0, 140)]
    assert recent_pace_samples(rows, start) == [(5.5, 130)]
