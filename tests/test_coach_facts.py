"""Invented activity inputs for the pure facts and intent rules."""

from copy import deepcopy

import pytest

from services.coach_facts import (
    build_data_notes,
    build_facts,
    detect_intent,
    match_text_facts,
    unsupported_text_numbers,
)


def context() -> dict:
    laps = [
        {"distance": 1.0, "duration": 6.8, "pace": pace, "avg_hr": hr, "avg_cadence": cadence}
        for pace, hr, cadence in ((6.8, 125, 160), (6.6, 130, 162), (6.5, 135, 164),
                                  (6.4, 140, 166), (6.2, 150, 168))
    ]
    laps.append({"distance": 3.2, "duration": 0.03, "pace": 0.01, "avg_hr": 151, "avg_cadence": 167})
    zones = [{"zone": f"Z{index} Invented", "percent": value}
             for index, value in enumerate((5.0, 50.0, 35.0, 10.0, 0.0), start=1)]
    return {
        "planned_intent": None,
        "recent_median_pace": "6:35",
        "active_goal": {"name": "Invented spring race"},
        "selected_activity": {
            "id": 10, "date": "2026-05-22", "distance_km": 5.0, "duration_min": 32.5,
            "pace": "6:30", "avg_hr": 135.2, "max_hr": 158,
            "aerobic_effect": 2.36, "anaerobic_effect": 0.04,
        },
        "lap_analysis": {"available": True, "laps": laps},
        "stream_analysis": {
            "available": True,
            "first_half": {"avg_pace": "6:40", "avg_hr": 130.4},
            "second_half": {"avg_pace": "6:20", "avg_hr": 140.4},
        },
        "metrics_snapshot": {
            "activity_session": {"hr_zones": zones, "hrmax": {"value": 200}},
            "readiness": {
                "score": {"value": 72.4},
                "components": [{"name": name, "score": {"value": score}}
                               for name, score in (("hrv", 60.2), ("rhr", 70.4),
                                                   ("sleep", 90.0), ("load", 80.5))],
            },
            "current_health": {
                "hrv": {"value": 60}, "resting_hr": {"value": 48},
                "sleep_duration": {"value": 7.5},
            },
            "baselines": [
                {"field": "hrv", "days": 28, "mean": {"value": 65}},
                {"field": "resting_hr", "days": 7, "mean": {"value": 50}},
                {"field": "sleep_duration", "days": 28, "mean": {"value": 7.0}},
            ],
            "load": {"ratio": {"value": 1.16}},
        },
    }


def as_map(facts):
    return {fact["id"]: fact for fact in facts}


def test_build_facts_formats_session_zones_kilometres_and_snapshot():
    facts = as_map(build_facts(10, context()))
    assert facts["DISTANCE"] == {"id": "DISTANCE", "metric": "Distance", "display": "5.0 km",
                                 "source": "selected_activity.distance_km"}
    assert facts["DURATION"]["display"] == "32:30"
    assert facts["AVG_HR"]["display"] == "135 bpm"
    assert facts["AVG_PACE"]["display"] == "6:30 /km"
    assert facts["AEROBIC_EFFECT"]["display"] == "2.4"
    assert facts["ANAEROBIC_EFFECT"]["display"] == "0.0"
    assert facts["ZONE_Z1"]["display"] == "5.0%"
    assert facts["ZONE_Z5"]["display"] == "0.0%"
    assert facts["Z3_PLUS_SHARE"]["display"] == "45.0%"
    assert facts["FIRST_HALF_PACE"]["display"] == "6:40 /km"
    assert facts["SECOND_HALF_HR"]["display"] == "140 bpm"
    assert facts["SPLIT_PATTERN"]["display"] == "negative split"
    assert facts["KM1_PACE"]["display"] == "6:48 /km"
    assert facts["KM5_AVG_HR"]["display"] == "150 bpm"
    assert facts["FIRST_FULL_KM"]["display"] == "km 1"
    assert facts["LAST_FULL_KM"]["display"] == "km 5"
    assert facts["CONSERVATIVE_START"]["display"] == "yes"
    assert facts["LAP_CADENCE_RANGE"]["display"] == "160–168 spm"
    assert facts["PARTIAL_LAP_DISTANCE"]["display"] == "3.20 m"
    assert facts["RECENT_MEDIAN_PACE"]["display"] == "6:35 /km"
    assert facts["READINESS"]["display"] == "72/100"
    assert facts["HRV_CURRENT"]["display"] == "60 ms"
    assert facts["HRV_BASELINE"]["display"] == "65 ms"
    assert facts["HRV_VS_BASELINE"]["display"] == "-7.7%"
    assert facts["RHR_BASELINE"]["display"] == "50 bpm"
    assert facts["RHR_VS_BASELINE"]["display"] == "-2 bpm"
    assert facts["SLEEP_CURRENT"]["display"] == "7:30 h"
    assert facts["SLEEP_VS_BASELINE"]["display"] == "+0:30 h"
    assert facts["LOAD_RATIO"]["display"] == "1.16"
    assert facts["LOAD_RATIO_STATUS"]["display"] == "in safe range 0.8–1.3"
    assert [facts[f"READINESS_{name}_SCORE"]["display"] for name in ("HRV", "RHR", "SLEEP", "LOAD")] == [
        "60.2/100", "70.4/100", "90.0/100", "80.5/100",
    ]
    for zone, lower, upper in (("Z1", "100 bpm", "119 bpm"), ("Z2", "120 bpm", "139 bpm"),
                               ("Z3", "140 bpm", "159 bpm"), ("Z4", "160 bpm", "179 bpm"),
                               ("Z5", "180 bpm", "no upper bpm limit")):
        assert facts[f"ZONE_{zone}_LOWER_BPM"]["display"] == lower
        assert facts[f"ZONE_{zone}_UPPER_BPM"]["display"] == upper


@pytest.mark.parametrize("ratio,status", [(0.79, "below"), (0.8, "in"), (1.3, "in"), (1.31, "above")])
def test_load_status_uses_readiness_safe_range(ratio, status):
    data = context()
    data["metrics_snapshot"]["load"]["ratio"]["value"] = ratio
    assert as_map(build_facts(10, data))["LOAD_RATIO_STATUS"]["display"] == f"{status} safe range 0.8–1.3"


def test_conservative_start_requires_slower_first_km_and_lower_hr():
    data = context()
    data["lap_analysis"]["laps"][0]["avg_hr"] = 140
    assert "CONSERVATIVE_START" not in as_map(build_facts(10, data))
    data["lap_analysis"]["laps"][0]["avg_hr"] = 125
    data["lap_analysis"]["laps"][0]["pace"] = 6.1
    assert "CONSERVATIVE_START" not in as_map(build_facts(10, data))


def test_build_facts_rejects_wrong_activity_and_omits_missing_values():
    data = context()
    with pytest.raises(ValueError, match="activity_id"):
        build_facts(11, data)
    data["selected_activity"]["max_hr"] = None
    data["metrics_snapshot"]["load"]["ratio"]["value"] = None
    facts = as_map(build_facts(10, data))
    assert "MAX_HR" not in facts and "LOAD_RATIO" not in facts and "LOAD_RATIO_STATUS" not in facts


@pytest.mark.parametrize("zones,avg_hr,last_km_hr,planned,expected", [
    ((5, 50, 35, 10, 0), 135, 150, None, "steady"),
    ((50, 45, 5, 0, 0), 125, 150, None, "recovery"),
    ((15, 70, 15, 0, 0), 140, 150, None, "easy"),
    ((15, 70, 15, 0, 0), 140, 170, None, None),
    ((5, 20, 45, 30, 0), 160, 165, None, "tempo"),
    ((0, 10, 30, 55, 5), 175, 180, None, "race"),
    ((15, 70, 15, 0, 0), 140, 150, "race", "race"),
])
def test_detect_intent_rule_precedence_and_fact_ids(zones, avg_hr, last_km_hr, planned, expected):
    data = context()
    for zone, value in zip(data["metrics_snapshot"]["activity_session"]["hr_zones"], zones, strict=True):
        zone["percent"] = value
    data["selected_activity"]["avg_hr"] = avg_hr
    data["lap_analysis"]["laps"][4]["avg_hr"] = last_km_hr
    data["planned_intent"] = planned
    facts = build_facts(10, data)
    decision = detect_intent(facts, planned)
    assert (decision.intent if decision else None) == expected
    if decision:
        assert set(decision.fact_ids) <= set(as_map(facts))


def test_detect_intent_needs_zone_evidence_except_planned_race():
    data = context()
    data["metrics_snapshot"]["activity_session"]["hr_zones"] = []
    facts = build_facts(10, data)
    assert detect_intent(facts, None) is None
    data["planned_intent"] = "race"
    facts = build_facts(10, data)
    assert detect_intent(facts, "race").fact_ids == ("PLAN_INTENT",)


def test_data_notes_short_lap_and_cadence_but_no_invented_gps_gap():
    data = context()
    points = [{"point_index": index, "elapsed_seconds": index * 2, "distance_km": index * 0.01,
               "cadence": 82} for index in range(5)]
    notes = build_data_notes(data["lap_analysis"]["laps"], points, 5.0)
    assert any("3.20 m" in note for note in notes)
    assert any("per-foot" in note for note in notes)
    assert not any("GPS" in note for note in notes)


@pytest.mark.parametrize("change", [
    {"elapsed_seconds": 40, "distance_km": 0.01},
    {"elapsed_seconds": 2, "distance_km": 0.25},
])
def test_data_notes_gps_only_for_observed_time_or_distance_gap(change):
    points = [{"point_index": 0, "elapsed_seconds": 0, "distance_km": 0.0},
              {"point_index": 1, **change}]
    notes = build_data_notes([], points, 5.0)
    assert len(notes) == 1 and "GPS data gap" in notes[0]


def test_data_notes_accepts_small_distance_already_in_km():
    notes = build_data_notes([{"distance": 0.0032, "duration": 0.03}], [], 5.0)
    assert notes == ["Partial lap: 3.20 m. Excluded from full-km analysis."]


def test_numeric_claims_need_display_value_with_spacing_normalized():
    facts = build_facts(10, context())
    assert unsupported_text_numbers("Z3+ was 45.0 % and pace was 6:30/km.", facts) == ()
    assert unsupported_text_numbers("Heart rate reached 149 bpm.", facts) == ("149",)
    assert unsupported_text_numbers("I ran 135 without units.", facts) == ("135",)


def test_match_text_facts_finds_uncited_display_and_rejects_new_number():
    facts = build_facts(10, context())
    matched, unsupported = match_text_facts("HR stayed under 139bpm; load is 1.88.", facts)
    assert "ZONE_Z2_UPPER_BPM" in matched
    assert unsupported == ("1.88",)


def test_facts_are_pure_and_do_not_mutate_context():
    data = context()
    before = deepcopy(data)
    first = build_facts(10, data)
    assert data == before
    assert first == build_facts(10, data)
