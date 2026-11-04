import json
import sqlite3
from dataclasses import replace
from datetime import date

import pytest
from fastapi.testclient import TestClient

from coach.proposals import apply, create_proposal, manual_session, undo_last
from coach.session_workouts import propose_move, read_session, use_shorter_variant
from config import get_settings
from db.migration_runner import upgrade_database
from services.morning_brief import format_workout_steps
from web.app import create_app
from web.view_models.session import session_detail


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "session-workouts.db"
    upgrade_database(path)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO users(id,max_hr,marathon_goal_time,running_goal_time) "
                   "VALUES(1,190,'04:00:00','04:00:00')")
        db.execute("INSERT INTO activities(user_id,date,type,distance,duration,avg_hr) "
                   "VALUES(1,'2026-11-03','running',5,1800,130)")
        db.execute("INSERT INTO health_metrics(user_id,date,resting_hr,hrv,sleep_duration) "
                   "VALUES(1,'2026-11-03',55,50,7)")
    return path


def workout():
    return {"type": "easy_base", "duration_min": 40, "title": "Easy run 40 min", "purpose": "Build aerobic consistency.",
            "why_session": "This supports your aerobic base.", "why_day": "It follows the rest day.",
            "how_it_feels": "conversational", "done_right_if": "You can speak in full sentences",
            "fallback": "Shorten to 30 min or take an easy day",
            "steps": [{"label": "Main set", "duration_min": 40, "hr_target": "110–130 bpm"}],
            "variants": {"shorter": {"duration_min": 30,
                                     "steps": [{"label": "Main set", "duration_min": 30}]}}}


def test_apply_and_undo_keep_all_workout_text(database):
    item = {"date": "2026-11-09", "sport": "running", "intent": "easy", "duration_min": 40,
            "hr_cap_bpm": 130, "notes": None, "workout_type": "easy_base", "workout": workout()}
    proposal = create_proposal(database, 1, "weekly_plan", "A plan", [
        {"id": "D", "metric": "Date", "display": "2026-11-09", "source": "fixture"}], [{
            "change_type": "add", "session": item, "reason": "This supports the session purpose.",
            "fact_ids": ["D"], "group_id": "day"}])
    apply(database, 1, proposal["id"], [proposal["changes"][0]["id"]])
    with sqlite3.connect(database) as db:
        row = db.execute("SELECT id,workout_json FROM plan_sessions WHERE date='2026-11-09'").fetchone()
    saved = json.loads(row[1])
    for field in ("purpose", "why_session", "why_day", "how_it_feels", "done_right_if", "fallback"):
        assert saved[field] == workout()[field]
    undo_last(database, 1)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT count(*) FROM plan_sessions WHERE date='2026-11-09'").fetchone()[0] == 0


def test_session_detail_structured_and_unstructured(database):
    item = {"date": "2026-11-09", "sport": "running", "intent": "easy", "duration_min": 40,
            "hr_cap_bpm": 130, "notes": None, "workout_type": "easy_base", "workout_json": json.dumps(workout())}
    session_id = manual_session(database, 1, item)
    assert session_detail(read_session(database, 1, session_id))["structured"]
    item["date"] = "2026-11-10"
    item.update(workout_type=None, workout_json=None)
    second = manual_session(database, 1, item)
    assert not session_detail(read_session(database, 1, second))["structured"]


def test_shorter_variant_is_saved_for_that_session(database):
    item = {"date": "2026-11-09", "sport": "running", "intent": "easy", "duration_min": 40,
            "hr_cap_bpm": 130, "notes": None, "workout_type": "easy_base", "workout_json": json.dumps(workout())}
    session_id = manual_session(database, 1, item)
    updated = use_shorter_variant(database, 1, session_id)
    assert updated["duration_min"] == 30
    assert json.loads(updated["workout_json"])["steps"][0]["duration_min"] == 30


def test_move_creates_grouped_proposal_without_moving_session(database):
    item = {"date": "2026-11-09", "sport": "running", "intent": "easy", "duration_min": 40,
            "hr_cap_bpm": 130, "notes": None, "workout_type": "easy_base", "workout_json": json.dumps(workout())}
    session_id = manual_session(database, 1, item)
    proposal = propose_move(database, 1, session_id, date(2026, 11, 11))
    assert len(proposal["changes"]) == 2
    assert proposal["changes"][0]["group_id"] == proposal["changes"][1]["group_id"]
    assert read_session(database, 1, session_id)["date"] == "2026-11-09"


def test_session_page_renders_workout_and_shorter_action(database):
    item = {"date": "2026-11-09", "sport": "running", "intent": "easy", "duration_min": 40,
            "hr_cap_bpm": 130, "notes": None, "workout_type": "easy_base", "workout_json": json.dumps(workout())}
    session_id = manual_session(database, 1, item)
    settings = replace(get_settings(), db_path=database, llm_provider="none")
    with TestClient(create_app(settings, password="")) as client:
        response = client.get(f"/training/session/{session_id}")
    assert response.status_code == 200
    assert "How it should feel" in response.text
    assert "Done right if" in response.text
    assert "Do the shorter version" in response.text


def test_morning_brief_includes_compact_planned_steps():
    text = format_workout_steps({"steps": [
        {"label": "Warm-up", "duration_min": 8, "hr_target": "92–110 bpm"},
        {"label": "Main set", "duration_min": 22, "pace_target": "6:10–6:30 /km"},
    ]})
    assert text == "Warm-up: 8 min at 92–110 bpm; Main set: 22 min, 6:10–6:30 /km"
