"""Synthetic plan safety, approval and import tests; no athlete database is used."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import date, timedelta

import pytest

from coach.planning import LoadModel, apply_draft, estimate_load, is_hard, validate_week
from coach.proposals import (apply, create_proposal, dismiss, get_proposal, get_week,
                             link_activity, list_commitments, list_proposals, manual_session,
                             materialize_week, request_revision, save_commitment, undo_last)
from coach.tools import CoachTools
from config import get_settings
from db.migration_runner import upgrade_database
from services.weekly_plan_service import scheduled_team_sports, todays_sessions

START = date(2026, 6, 29)
FACTS = [{"id": "TRAINING_LOAD", "metric": "Load", "display": "200.0 TRIMP", "source": "metrics.sessions.load"}]


def session(day: date, sport: str = "running", intent: str = "easy", minutes: int = 30,
            identifier: int | None = None) -> dict:
    return {"id": identifier, "date": day.isoformat(), "sport": sport, "intent": intent,
            "duration_min": minutes, "hr_cap_bpm": 130 if sport == "running" else None, "notes": None}


def change(day: date, *, action: str = "add", sport: str = "running", intent: str = "easy",
           minutes: int = 30, identifier: int | None = None) -> dict:
    return {"change_type": action, "session": session(day, sport, intent, minutes, identifier),
            "reason": "Keep the week controlled.", "fact_ids": ["TRAINING_LOAD"]}


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "plan.db"
    upgrade_database(path)
    with sqlite3.connect(path) as connection:
        connection.execute("INSERT INTO users(id,age,max_hr,marathon_goal_time,running_goal_time) "
                           "VALUES(1,30,190,'04:00:00','04:00:00')")
        connection.execute("INSERT INTO users(id,age,max_hr,marathon_goal_time,running_goal_time) "
                           "VALUES(2,30,190,'04:00:00','04:00:00')")
        for offset in range(35):
            day = START - timedelta(days=35 - offset)
            connection.execute("INSERT INTO health_metrics(user_id,date,resting_hr,hrv,sleep_duration) "
                               "VALUES(1,?,?,?,?)", (day.isoformat(), 55, 50, 7.5))
        for offset in (7, 14, 21, 28):
            connection.execute("INSERT INTO activities(user_id,date,type,distance,duration,avg_hr) "
                               "VALUES(1,?,'running',10,3600,135)", ((START - timedelta(days=offset)).isoformat(),))
    return path


def test_pure_week_rules_and_boundaries():
    model = LoadModel(100, {("running", "easy"): 1, ("running", "tempo"): 2,
                            ("volleyball", "training"): 1}, {"running": 1, "volleyball": 1})
    assert estimate_load(session(START, minutes=30), model) == 30
    assert estimate_load(session(START, sport="gym"), model) is None
    assert is_hard(session(START, intent="tempo"))
    assert is_hard(session(START, sport="volleyball", intent="training"))
    assert not is_hard(session(START, sport="volleyball", intent="skills only"))
    assert validate_week([session(START, minutes=110)], model, today=START + timedelta(days=7), decisions={}) == []
    assert any("110%" in error for error in validate_week(
        [session(START, minutes=111)], model, today=START + timedelta(days=7), decisions={}))
    hard = [session(START + timedelta(days=n), intent="tempo") for n in (0, 1)]
    assert "Hard days are consecutive" in validate_week(hard, model, today=START + timedelta(days=7), decisions={})
    hard = [session(START + timedelta(days=n), intent="tempo") for n in (0, 2, 4)]
    assert "More than two hard days" in validate_week(hard, model, today=START + timedelta(days=7), decisions={})
    assert any("rest" in error for error in validate_week(
        [session(START)], model, today=START, decisions={START: "rest"}))
    assert any("easy" in error for error in validate_week(
        [session(START, intent="tempo")], model, today=START, decisions={START: "easy"}))
    assert apply_draft([], [change(START)])[0]["origin"] == "coach"


def test_fixed_commitments_and_read_only_week(database):
    commitment_id = save_commitment(database, 1, weekday=1, start_time="19:00", sport="volleyball",
                                    kind="training", duration_min=90)
    assert list_commitments(database, 1)[0]["id"] == commitment_id
    assert get_week(database, 1, START)["sessions"][0]["origin"] == "fixed"
    assert scheduled_team_sports(START + timedelta(days=1), settings=replace(get_settings(), db_path=database)) == (
        "volleyball",)
    assert len(todays_sessions(START + timedelta(days=1), settings=replace(get_settings(), db_path=database))) == 1
    assert materialize_week(database, 1, START) == 1
    assert materialize_week(database, 1, START) == 0
    assert CoachTools(database, 1, "Europe/Berlin", 7.5).plan_week(START)["sessions"][0]["fixed"]
    with pytest.raises(ValueError, match="Fixed commitments"):
        apply_draft(get_week(database, 1, START)["sessions"], [change(
            START + timedelta(days=1), action="remove", sport="volleyball", intent="training",
            identifier=get_week(database, 1, START)["sessions"][0]["id"])])
    save_commitment(database, 1, weekday=1, start_time="19:00", sport="volleyball", kind="training",
                    duration_min=90, active=False, commitment_id=commitment_id)
    assert scheduled_team_sports(START + timedelta(days=1), settings=replace(get_settings(), db_path=database)) == (
        "volleyball",)  # Existing dated session remains until the athlete changes it.


def test_partial_approval_stale_and_undo_preserves_athlete_edit(database):
    before_activities = sqlite3.connect(database).execute("SELECT * FROM activities").fetchall()
    first = create_proposal(database, 1, "weekly_plan", "Easy week", FACTS,
                            [change(START), change(START + timedelta(days=2))])
    older = create_proposal(database, 1, "change", "Older idea", FACTS, [change(START + timedelta(days=4))])
    assert get_week(database, 1, START)["sessions"] == []
    result = apply(database, 1, first["id"], [first["changes"][0]["id"]])
    assert result["status"] == "partially_applied"
    assert [item["decision"] for item in result["changes"]] == ["accepted", "rejected"]
    manual_session(database, 1, session(START + timedelta(days=5)))
    with pytest.raises(ValueError, match="stale"):
        apply(database, 1, older["id"], [older["changes"][0]["id"]])
    assert get_proposal(database, 1, older["id"])["status"] == "stale"
    undo_last(database, 1)
    remaining = get_week(database, 1, START)["sessions"]
    assert [item["date"] for item in remaining] == [(START + timedelta(days=5)).isoformat()]
    assert sqlite3.connect(database).execute("SELECT * FROM activities").fetchall() == before_activities


def test_revision_dismiss_and_user_boundary(database):
    proposal = create_proposal(database, 1, "change", "Try easy", FACTS, [change(START)])
    revised = request_revision(database, 1, proposal["id"], "Move the easy session", [change(START + timedelta(days=1))])
    assert revised["status"] == "pending"
    assert get_proposal(database, 1, proposal["id"])["status"] == "superseded"
    dismiss(database, 1, revised["id"])
    assert get_proposal(database, 1, revised["id"])["status"] == "dismissed"
    assert list_proposals(database, 2, START) == []
    with pytest.raises(ValueError, match="not found"):
        get_proposal(database, 2, revised["id"])


def test_link_activity_marks_plan_done_without_editing_activity(database):
    session_id = manual_session(database, 1, session(START))
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO activities(user_id,date,type,distance,duration) VALUES(1,?,'running',5,1800)",
                           (START.isoformat(),))
        activity_id = connection.execute("SELECT max(id) FROM activities").fetchone()[0]
        assert link_activity(connection, 1, activity_id, START, "running")
        assert not link_activity(connection, 1, activity_id, START, "running")
    row = sqlite3.connect(database).execute("SELECT status,linked_activity_id FROM plan_sessions WHERE id=?",
                                             (session_id,)).fetchone()
    assert row == ("done", activity_id)


def test_proposal_rejects_unknown_facts_and_unsupported_numbers(database):
    invalid = change(START)
    invalid["fact_ids"] = ["UNKNOWN"]
    with pytest.raises(ValueError, match="known facts"):
        create_proposal(database, 1, "change", "Invalid", FACTS, [invalid])
    invalid["fact_ids"] = ["TRAINING_LOAD"]
    invalid["reason"] = "Run 123 minutes."
    with pytest.raises(ValueError, match="absent"):
        create_proposal(database, 1, "change", "Invalid", FACTS, [invalid])
