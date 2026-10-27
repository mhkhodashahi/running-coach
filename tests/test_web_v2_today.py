"""Milestone 5e-1b presentation tests with invented values only."""

from datetime import date
from types import SimpleNamespace

from web.view_models.today import (
    TODAY_FOLLOW_UPS,
    call_headline,
    coach_evidence,
    dial_models,
    dial_status,
    display_decision_text,
    display_duration,
    format_chip,
    purpose_line,
    session_name,
    week_strip,
    workout_model,
)


def test_dial_words_and_missing_data():
    assert dial_status("recovery", 72, None) == ("Good", "check")
    assert dial_status("recovery", 55, None) == ("Fair", "minus")
    assert dial_status("recovery", 38, None) == ("Low", "down")
    assert dial_status("sleep", 8, 7) == ("Above usual", "up")
    assert dial_status("sleep", 6, 7) == ("Below usual", "down")
    assert dial_status("sleep", 7, 7) == ("Normal", "minus")
    assert dial_status("load", 110, 100) == ("Normal", "minus")
    assert dial_status("load", 140, 100) == ("Above usual", "up")
    dials = dial_models(None, None, None, None, None, "Synced 08:00")
    assert all(item["value"] == "No data" and item["usual"] == "Synced 08:00" for item in dials)
    assert all(item["percent"] == 0 for item in dials)
    complete = dial_models(72, 8, 7, 80, 100, "Synced 08:00")
    assert complete[1]["usual"] == "usual 7h 00m"
    assert complete[2]["spoken_value"] == "80% of usual" and complete[2]["usual"] is None


def test_call_headline_purpose_and_duration():
    assert session_name("running", "tempo") == "tempo run"
    assert session_name("gym", "light upper body") == "light gym"
    assert call_headline("hard", {"title": "tempo run"}) == "Hard day — tempo run"
    assert call_headline("easy", {"title": "easy run"}) == "Easy day — easy run"
    assert call_headline("rest", None) == "Rest day"
    assert display_duration(30) == "30 min"
    assert display_duration(None) is None
    dials = dial_models(72, 8, 7, 70, 100, "Synced 08:00")
    assert purpose_line(None, dials) == "You're recovered and your load is below usual."
    assert purpose_line({"purpose": "Build easy endurance"}, dials) == (
        "Build easy endurance. You're recovered and your load is below usual.")
    assert "0.70" not in purpose_line(None, dials)


def test_evidence_chips_have_one_label_and_unit():
    source = "metrics_snapshot.load.ratio"
    assert format_chip({"id": "READINESS", "metric": "Readiness", "display": "72/100", "source": source}) == {
        "label": "Recovery", "value": "72", "source": source}
    assert format_chip({"id": "LOAD_RATIO", "metric": "Load ratio", "display": "0.72", "source": source}) == {
        "label": "Load", "value": "72% of usual", "source": source}
    assert format_chip({"id": "HARD_LAST_48H", "metric": "Hard session in last 48h",
                        "display": "no hard session in the last 48 hours", "source": source}) == {
        "label": "Last hard session:", "value": "none in the last 48 hours", "source": source}
    assert format_chip({"id": "OTHER", "metric": "Training load", "display": "Training load high",
                        "source": source})["value"] == "high"
    facts = ({"id": "READINESS", "metric": "Readiness", "display": "72/100", "source": source},)
    evidence = coach_evidence(SimpleNamespace(facts=facts, evidence_ids=("READINESS", "UNKNOWN"), rule_fact_ids=()))
    assert evidence[0]["label"] == "Recovery" and evidence[0]["value"] == "72"
    assert len(TODAY_FOLLOW_UPS) == 3


def test_decision_text_is_web_only_wording():
    stored = "Your readiness is 72/100 and your load ratio is 0.72. No hard session in the last 48 hours."
    shown = display_decision_text(stored)
    assert stored.startswith("Your readiness")
    assert shown == "Recovery is 72 and load is 72% of usual. No hard session in the last 48 hours."
    assert "readiness" not in shown.lower() and "load ratio" not in shown.lower()
    assert display_decision_text("Load ratio 0.80 and readiness 64/100.") == (
        "Load is 80% of usual and recovery is 64.")
    assert display_decision_text("Recent load is within range (ratio 0.80).") == (
        "Recent load is within range (load is 80% of usual).")


def test_week_strip_done_and_planned_are_both_visible():
    day = date(2026, 10, 27)
    sessions = [
        {"date": "2026-10-27", "sport": "running", "intent": "tempo", "status": "planned",
         "duration_min": 30, "origin": "coach", "linked_activity_id": None},
        {"date": "2026-10-29", "sport": "gym", "intent": "light", "status": "planned",
         "duration_min": 30, "origin": "protected", "linked_activity_id": None},
        {"date": "2026-11-01", "sport": "rest", "intent": "recovery", "status": "planned",
         "duration_min": 15, "origin": "athlete", "linked_activity_id": None},
    ]
    activities = [{"id": 9, "date": "2026-10-27", "sport": "gym"}]
    days = week_strip(day, sessions, activities, unrated_id=9)
    assert len(days) == 7
    assert days[1]["state"] == "done today"
    assert [(item["title"], item["done"]) for item in days[1]["entries"]] == [
        ("Gym", True), ("Tempo run", False)]
    assert days[1]["entries"][0]["rate_id"] == 9
    assert days[1]["entries"][1]["duration"] == "30 min"
    assert days[1]["phone_title"] == "Tempo"
    assert days[1]["phone_done"] == "Gym"
    assert days[3]["phone_title"] == "Light gym"
    assert days[-1]["phone_title"] == "Rest"
    assert days[0]["phone_title"] == "—"
    assert days[2]["state"] == "empty" and days[2]["title"] == "Nothing planned"
    assert days[3]["entries"][0]["origin"] == "protected"
    assert days[6]["state"] == "rest" and days[6]["title"] == "Rest day"
    assert days[6]["day_label"] == "Sun 1"


def test_today_recommendation_appears_beside_done_activity():
    day = date(2026, 10, 27)
    result = week_strip(day, [], [{"id": 9, "date": day.isoformat(), "sport": "gym"}], 9,
                        {"title": "tempo run", "duration": "30 min"})
    assert [entry["title"] for entry in result[1]["entries"]] == ["Gym", "Tempo run"]


def test_workout_uses_planned_session_and_code_facts():
    decision = SimpleNamespace(date="2026-10-27", athlete_choice=None, intensity="easy", sports=(
        {"sport": "running", "session": {"intent": "easy", "duration_min": 30, "structure": "HR under 130 bpm"}},))
    planned = [{"date": "2026-10-27", "sport": "gym", "intent": "light", "status": "planned",
                "duration_min": 40, "purpose": "Work on strength"}]
    assert workout_model(decision, planned)["title"] == "light gym"
    assert workout_model(decision, planned)["duration"] == "40 min"
    assert workout_model(decision, planned)["steps"] == ()
    assert workout_model(decision, [])["structure"] == "HR under 130 bpm"
    assert workout_model(SimpleNamespace(**{**vars(decision), "intensity": "rest"}), planned) is None
