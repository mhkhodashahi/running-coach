"""V2 Insights and Activity view models use invented, dated data only."""

import json

from services.coach_opinion import load_opinion
from web.charts import plot_only, trend_line, weekly_percent_bars
from web.view_models.activity import (
    activity_tabs,
    build_activity_view,
    comparison_columns,
    difference_words,
    display_opinion,
    list_row,
    opinion_preview,
    sport_numbers,
)
from web.view_models.insights import axis_dates, build_insights_view, gap_note, summary_sentences


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


def _previous():
    return {"rhr": _series([54, 54, 54]), "hrv": _series([55, 55, 55]),
            "sleep": _series([7.5, 7.5, 7.5])}


def test_insights_summary_words_first_uses_usual_and_gaps():
    data = _insights_data()
    data["previous"] = _previous()
    series = {**data["series"], "rhr": _series([58, None, 60]),
              "hrv": _series([48, None, 50])}
    summary = summary_sentences(series, data["previous"], 80, data["sync"])
    assert "Resting HR averaged 5 bpm higher and HRV averaged 6 ms lower" in summary
    assert "previous 3 days" in summary
    assert "80% of usual" in summary
    assert summary.count(".") == 2
    assert "Recovery has changed:" not in summary and "is +" not in summary
    assert gap_note(data["series"]["rhr"]) == "1 day without data"
    view = build_insights_view(data, ("running_goal", 10), [(5, 30), (7, 45)], 7.5)
    assert len(view["metric_cards"]) == 5
    assert view["metric_cards"][0]["title"] == "Recovery"
    assert view["metric_cards"][1]["usual"] == "usual 7h 30m"
    assert view["metric_cards"][2]["status"] == "Normal"
    assert view["metric_cards"][2]["gap_note"] == "1 day without data"
    assert "Nothing changed much" in view["panel_summary"]
    assert view["metric_cards"][0]["caption"] == "today"
    assert view["metric_cards"][1]["caption"] == "last night"
    assert view["metric_cards"][4]["caption"] == "this week"
    data["series"]["readiness"] = _series([72, 80, None])
    assert build_insights_view(data, None, [], None)["metric_cards"][0]["caption"] == "latest: Fri 2 Oct"
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
    assert view["summary_text"] == "Not enough data in the previous 3 days to compare."


def test_activity_sport_specific_numbers_and_tabs():
    stats = [("Distance", "5.0 km"), ("Time", "27 min"), ("Avg pace", "5:24 /km"),
             ("Avg HR", "145 bpm"), ("Session load", "70 load"), ("Cadence", "168 spm")]
    run, secondary = sport_numbers(stats, "running", "Synced 09:00")
    assert [item["value"] for item in run] == ["5.0 km", "27 min", "5:24 /km", "145 bpm"]
    assert "Cadence 168 spm" in secondary
    gym, _ = sport_numbers([("Duration", "30 min"), ("Avg HR", "120 bpm"),
                           ("Session load", "42 load")], "gym", "Synced 09:00")
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
                         ("Session load", "65 load")], "opinion": None,
               "laps": [], "similar": [], "sync": "Synced 09:00"}
    facts = [{"id": "ACT_42_DURATION", "metric": "Duration", "display": "1h 30m", "source": "fixture"},
             {"id": "ACT_42_AVG_HR", "metric": "Avg HR", "display": "130 bpm", "source": "fixture"}]
    view = build_activity_view(context, facts)
    assert view["team_note"] is True
    assert "1h 30m" in view["coach_summary"]
    assert len(view["fact_chips"]) == 2


def test_legacy_review_rendering_is_structured_and_does_not_mutate_payload():
    payload = {"brutally_honest_conclusion": "Keep it steady. Rest next.",
               "overall_assessment": "Keep it steady. The effort was controlled.",
               "pacing_analysis": {"avg_pace": "5:58", "hr_drift": 16.4,
                                   "zone_distribution": {"Z3": 58}},
               "recovery_analysis": [{"sleep_duration": "7h 20m"}, "Rested"]}
    raw = json.dumps(payload)
    opinion = load_opinion({"payload_json": raw, "schema_version": None}).model_dump()
    view = display_opinion(opinion, payload, legacy=True)
    assert view["headline"] == "Keep it steady."
    assert view["assessment"] == "The effort was controlled."
    assert view["conclusion"] == "Rest next."
    assert ("Avg pace", "5:58 /km") in view["section_rows"]["pacing"]
    assert ("HR drift", "16.4 bpm") in view["section_rows"]["pacing"]
    assert ("Z3", "58%") in view["section_rows"]["pacing"]
    assert json.dumps(payload) == raw
    long = "This sentence is long " * 10 + ". And another."
    assert len(display_opinion({**opinion, "headline": long}, payload, legacy=True)["headline"]) <= 120


def test_legacy_json_text_sections_render_as_rows_and_bullets():
    payload = {"pacing_analysis": json.dumps({"avg_pace": "5:58", "zone_distribution": {"Z3": 58}}),
               "mental_performance_insights": json.dumps(["Steady focus", "Relaxed finish"])}
    raw = json.dumps(payload)
    opinion = load_opinion({"payload_json": raw, "schema_version": None}).model_dump()
    view = display_opinion(opinion, payload, legacy=True)
    assert ("Avg pace", "5:58 /km") in view["section_rows"]["pacing"]
    assert ("Z3", "58%") in view["section_rows"]["pacing"]
    assert view["section_rows"]["mental"] == (("", "Steady focus"), ("", "Relaxed finish"))
    assert view["sections"]["mental"] == ""
    assert json.dumps(payload) == raw


def test_legacy_numeric_strings_get_sport_units_and_long_headline_dedupes():
    sentence = "A deliberately long first sentence " * 5 + "ends here."
    payload = {"brutally_honest_conclusion": sentence + " Next step.",
               "overall_assessment": sentence + " The rest is new.",
               "recovery_analysis": json.dumps({"hrv": "50.0", "avg_hr": "144.0",
                                                "sleep_duration": "5.5 h"}),
               "aerobic_efficiency_analysis": json.dumps({"zone_3_steady": "58.1",
                                                           "zone_distribution": {"Zone 3 Steady/Aerobic": "58.0"},
                                                           "hr_drift_bpm": "16.4"})}
    opinion = load_opinion({"payload_json": json.dumps(payload), "schema_version": None}).model_dump()
    view = display_opinion(opinion, payload, legacy=True)
    assert len(view["headline"]) <= 120
    assert view["assessment"] == "The rest is new."
    assert ("HRV", "50 ms") in view["section_rows"]["recovery"]
    assert ("Avg HR", "144 bpm") in view["section_rows"]["recovery"]
    assert ("Sleep duration", "5h 30m") in view["section_rows"]["recovery"]
    assert ("Z3", "58%") in view["section_rows"]["aerobic"]
    assert ("HR drift", "16.4 bpm") in view["section_rows"]["aerobic"]
    assert ("Z3", "58%") in view["section_rows"]["aerobic"]


def test_axis_thinning_and_unscaled_plot_text():
    days = [(f"2026-01-{day:02d}", float(day)) for day in range(1, 29)]
    assert len(axis_dates(days)) == 5
    assert axis_dates(days)[0] == "Thu 1 Jan"
    weeks = [(f"2026-{month:02d}-01", float(month)) for month in range(1, 13)]
    assert len(axis_dates(weeks)) <= 5
    for chart in (trend_line(days, "Recovery", "muted"), weekly_percent_bars(weeks)):
        assert "<text" not in plot_only(chart["svg"])


def test_other_sport_has_generic_icon():
    assert list_row("Swim", "other", None, 12, "Synced 09:00")["icon"] == "activity"


def test_summary_changes_with_selected_range():
    for days in (7, 28, 90):
        current = {key: [(f"2026-01-{index % 28 + 1:02d}", float(60 + days / 10 + index % 2))
                         for index in range(days)] for key in ("rhr", "hrv", "sleep")}
        earlier = {key: [("2025-12-01", 50.0)] * days for key in current}
        text = summary_sentences(current, earlier, 75, "Synced 09:00")
        assert f"previous {days} days" in text
        if days == 7:
            first = text
        else:
            assert text != first


def test_insights_requires_half_coverage_and_ignores_small_changes():
    current = {key: _series([50, 50, 50, 50, 50, 50, 50]) for key in ("rhr", "hrv", "sleep")}
    previous = {key: _series([50, None, None, None, None, None, None]) for key in current}
    assert summary_sentences(current, previous, 50, "Synced 09:00") == (
        "Not enough data in the previous 7 days to compare.")
    previous = {key: _series([50] * 7) for key in current}
    assert "Nothing changed much" in summary_sentences(current, previous, None, "Synced 09:00")
    assert "Nothing changed much" in build_insights_view(
        {**_insights_data(), "series": {**_insights_data()["series"], "rhr": _series([50] * 3),
                                   "hrv": _series([50] * 3), "sleep": _series([50] * 3)},
         "previous": {key: _series([50] * 3) for key in current}}, None, [], None)["panel_summary"]


def test_panel_ranks_mixed_units_by_own_variation_not_raw_delta():
    current = {"rhr": _series([54] * 7), "hrv": _series([58] * 7),
               "sleep": _series([7.05] * 7)}
    previous = {"rhr": _series([50] * 7), "hrv": _series([50] * 7),
                "sleep": _series([7] * 7)}
    from web.view_models.insights import panel_summary

    assert "resting hr" in panel_summary(current, previous, "Synced 09:00").lower()
    assert "8 ms" not in panel_summary(current, previous, "Synced 09:00")


def test_weekly_building_bars_are_muted_and_cannot_set_axis_maximum():
    chart = weekly_percent_bars([("2026-09-28", 400), ("2026-10-05", 90)], {"2026-09-28"})
    assert chart["y_max"] == 130
    assert 'fill="var(--ink-muted)"' in chart["svg"]
    assert "baseline still building" in chart["summary"]
    data = _insights_data()
    data["reference_week_counts"] = {"2026-09-28": 3, "2026-10-05": 4}
    assert build_insights_view(data, None, [], None)["metric_cards"][4]["baseline_note"] == (
        "baseline still building")


def test_activity_chips_duration_and_comparison_wording():
    context = {"activity": {"id": 42, "category": "gym", "sport": "Gym"},
               "stats": [("Duration", "25 min"), ("Avg HR", "130 bpm")],
               "opinion": None, "laps": [], "similar": [], "sync": "Synced 09:00"}
    facts = [{"id": "ACT_42_DISTANCE", "metric": "Distance", "display": "0.0 km"},
             {"id": "ACT_42_DURATION", "metric": "Duration", "display": "25:10"},
             {"id": "ACT_42_AVG_HR", "metric": "Avg HR", "display": "130 bpm"}]
    view = build_activity_view(context, facts)
    assert "25 min" in view["coach_summary"]
    assert view["fact_chips"] == ({"label": "Duration", "value": "25 min"},
                                   {"label": "Avg HR", "value": "130 bpm"})
    facts[1]["display"] = "1:23 h"
    long_view = build_activity_view(context, facts)
    assert "1h 23m" in long_view["coach_summary"]
    assert long_view["fact_chips"][0]["value"] == "1h 23m"
    assert difference_words("-22 s/km", None, "+27 bpm") == "22 s/km faster · 27 bpm higher"
    assert difference_words(None, "−12 min", "-5 bpm") == "12 min shorter · 5 bpm lower"
    assert comparison_columns([{"duration": "25 min", "hr": None, "load": "12",
                                "difference": "12 min shorter", "efficiency": None}], "gym") == {
        "measure": "Duration", "measure_visible": True, "hr": False, "load": True,
        "difference": True, "status": False}


def test_generated_summary_builders_keep_metric_casing():
    import re

    from web.view_models.insights import panel_summary
    from web.view_models.today import purpose_line
    from web.view_models.training import coach_summary

    current = {"rhr": _series([54] * 7), "hrv": _series([58] * 7),
               "sleep": _series([7.5] * 7)}
    previous = {"rhr": _series([50] * 7), "hrv": _series([50] * 7),
                "sleep": _series([7.5] * 7)}
    training, _ = coach_summary({"hard_count": 0, "rest_count": 1, "total_percent": 90,
                                 "load_status": "Normal", "suggested_hard_title": None,
                                 "suggested_title": None, "with_suggested_percent": None,
                                 "planned_hard_count": 0})
    today = purpose_line({"purpose": "Keep HR under Z2"},
                         ({"kind": "recovery", "status": "Good"},
                          {"kind": "load", "status": "Normal"}))
    outputs = (summary_sentences(current, previous, 90, "Synced 09:00"),
               panel_summary(current, previous, "Synced 09:00"), training, today)
    assert "HRV" in outputs[0] and ("HR" in outputs[1] or "HRV" in outputs[1])
    assert "HR under Z2" in today
    assert all(not re.search(r"\b(?:hrv|hr|z2)\b", text) for text in outputs)
