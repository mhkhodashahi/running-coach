"""V2 Insights and Activity view models use invented, dated data only."""

import json

from services.coach_opinion import load_opinion
from web.view_models.activity import activity_tabs, build_activity_view, opinion_preview, sport_numbers
from web.view_models.insights import build_insights_view, gap_note, summary_sentences


def _series(values):
    return [(f"2026-10-{day:02d}", value) for day, value in enumerate(values, 1)]


def _insights_data():
    return {"series": {"readiness": _series([72, None, 80]), "rhr": _series([54, None, 56]),
                       "hrv": _series([55, None, 52]), "sleep": _series([7.5, None, 7]),
                       "ratio": _series([1, None, .8])},
            "baselines": {"rhr": _series([54, 54, 54]), "hrv": _series([55, 55, 55]),
                          "sleep": _series([7.5, 7.5, 7.5])},
            "weekly": {"2026-09-28": {"running": 50}, "2026-10-05": {"running": 80}},
            "reference": 100, "sync": "Synced 09:00"}


def test_insights_summary_words_first_uses_usual_and_gaps():
    data = _insights_data()
    summary = summary_sentences(data["series"], data["baselines"], 80, data["sync"])
    assert "Resting HR +2 bpm vs usual" in summary
    assert "HRV \u22123 ms vs usual" in summary
    assert "80% of usual" in summary
    assert summary.count(".") == 2
    assert gap_note(data["series"]["rhr"]) == "1 day without data"
    view = build_insights_view(data, ("running_goal", 10), [(5, 30), (7, 45)], 7.5)
    assert len(view["metric_cards"]) == 5
    assert view["metric_cards"][0]["title"] == "Recovery"
    assert view["metric_cards"][1]["usual"] == "usual 7h 30m"
    assert view["metric_cards"][2]["status"] == "Normal"
    assert view["metric_cards"][2]["gap_note"] == "1 day without data"
    assert "HRV is \u22123 ms vs usual while resting HR is +2 bpm vs usual" in view["panel_summary"]
    assert view["goal_view"] == {"title": "Running \u00b7 10K goal", "runs": 2,
                                 "distance": "12.0 km", "longest": "45 min"}
    assert 'role="img"' in view["metric_cards"][4]["chart"]["svg"]
    assert "1 missing" in view["metric_cards"][0]["chart"]["summary"]


def test_insights_missing_values_are_not_zero_and_goal_is_optional():
    data = _insights_data()
    data["series"] = {key: _series([None, None, None]) for key in data["series"]}
    data["weekly"] = {"2026-10-05": {}}
    view = build_insights_view(data, None, [], None)
    assert view["goal_view"] is None
    assert all(card["value"] == "No data" for card in view["metric_cards"])
    assert all(card["missing"] == "Synced 09:00" for card in view["metric_cards"])
    assert "No data" in view["summary_text"]


def test_activity_sport_specific_numbers_and_tabs():
    stats = [("Distance", "5.0 km"), ("Time", "27m"), ("Avg pace", "5:24 /km"),
             ("Avg HR", "145 bpm"), ("Session load", "70 TRIMP"), ("Cadence", "168 spm")]
    run, secondary = sport_numbers(stats, "running", "Synced 09:00")
    assert [item["value"] for item in run] == ["5.0 km", "27m", "5:24 /km", "145 bpm"]
    assert "Cadence 168 spm" in secondary
    gym, _ = sport_numbers([("Duration", "30m"), ("Avg HR", "120 bpm"),
                           ("Session load", "42 TRIMP")], "gym", "Synced 09:00")
    assert [item["label"] for item in gym] == ["Duration", "Avg heart rate", "Session load"]
    assert [item["label"] for item in activity_tabs(None, [], [])] == ["Overview"]
    assert [item["label"] for item in activity_tabs({"headline": "Review"}, [{}], [{}])] == [
        "Overview", "Coach review", "Laps", "Compare"]


def test_activity_legacy_preview_and_missing_numbers():
    raw = json.dumps({"overall_assessment": "Steady work", "brutally_honest_conclusion": "Keep it steady. Rest next."})
    legacy = load_opinion({"payload_json": raw, "schema_version": None}).model_dump()
    assert opinion_preview(legacy) == {"headline": "Keep it steady.", "verdicts": (), "legacy": True}
    assert raw == json.dumps({"overall_assessment": "Steady work",
                              "brutally_honest_conclusion": "Keep it steady. Rest next."})
    assert opinion_preview(None) is None
    missing, _ = sport_numbers([("Duration", None), ("Avg HR", None)], "football", "Synced 09:00")
    assert all(item["value"] == "No data \u00b7 Synced 09:00" for item in missing)


def test_activity_coach_summary_and_team_note():
    context = {"activity": {"id": 42, "category": "volleyball", "sport": "Volleyball"},
               "stats": [("Duration", "1h 30m"), ("Avg HR", "130 bpm"),
                         ("Session load", "65 TRIMP")], "opinion": None,
               "laps": [], "similar": [], "sync": "Synced 09:00"}
    facts = [{"id": "ACT_42_DURATION", "metric": "Duration", "display": "1h 30m", "source": "fixture"},
             {"id": "ACT_42_AVG_HR", "metric": "Avg HR", "display": "130 bpm", "source": "fixture"}]
    view = build_activity_view(context, facts)
    assert view["team_note"] is True
    assert "1h 30m" in view["coach_summary"]
    assert len(view["fact_chips"]) == 2
