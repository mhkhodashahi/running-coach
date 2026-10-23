"""Synthetic weekly-plan, approval, undo and user-boundary tests."""

import json
import sqlite3
from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from coach.plan import draft_week, interpret_revision, make_session, monday, projected_plan_load
from coach.tools import CoachTools
from config import get_settings
from db.migration_runner import upgrade_database
from services.daily_decision_service import get_or_create_daily_decision
from services.weekly_plan_service import (
    accept_change,
    get_proposal,
    get_weekly_plan,
    list_proposals,
    propose_week,
    reject_change,
    revise_proposal,
    scheduled_team_sports,
    set_fixed_commitment,
    undo_last_coach_change,
)

START = date(2026, 6, 29)


def test_monday_session_and_revision_parser():
    assert monday(date(2026, 7, 2)) == START
    assert make_session("running", hr_cap_bpm=130)["intent"] == "easy"
    assert make_session("football", fixed=True)["fixed"]
    with pytest.raises(ValueError, match="Choose running"):
        make_session("walking")
    with pytest.raises(ValueError, match="HR cap"):
        make_session("running", hr_cap_bpm=999)
    assert interpret_revision("Make Saturday a rest day", START, 130) == (date(2026, 7, 4), None)
    day, session = interpret_revision("Put an easy run on Thursday", START, 130)
    assert day == date(2026, 7, 2)
    assert session == make_session("running", hr_cap_bpm=130)
    with pytest.raises(ValueError, match="Name one weekday"):
        interpret_revision("Move Monday to Friday", START, 130)
    with pytest.raises(ValueError, match="positive instruction"):
        interpret_revision("Do not make Saturday rest", START, 130)
    with pytest.raises(ValueError, match="not both"):
        interpret_revision("Make Saturday rest and run", START, 130)
    with pytest.raises(ValueError, match="Only easy running"):
        interpret_revision("Make Saturday a tempo run", START, 130)


def test_draft_is_bounded_by_history_and_preserves_fixed_days():
    existing = {START.isoformat(): make_session("football", duration_min=60, fixed=True)}
    draft = draft_week(START, START, 3, 120, existing, 130)
    assert [day.weekday() for day, _ in draft] == [2, 5]
    assert sum(session["duration_min"] for _, session in draft) + 60 <= 120
    assert all(session["intent"] == "easy" for _, session in draft)
    assert not draft_week(START, START, 3, 0, {}, 130)
    assert not draft_week(START, START, 0, 120, {}, 130)
    assert draft_week(START, START, 3, 120, {}, 130, rest_today=True)[0][0] != START
    with pytest.raises(ValueError, match="Monday"):
        draft_week(START + timedelta(days=1), START, 3, 120, {}, 130)
    limited = draft_week(START, START, 3, 120, {}, 130, load_budget=50,
                         load_rates={"running": 2})
    assert len(limited) == 1
    assert limited[0][1]["duration_min"] == 25
    assert projected_plan_load({limited[0][0].isoformat(): limited[0][1]}, {"running": 2}) == 50
    assert projected_plan_load({START.isoformat(): make_session("gym")}, {"running": 2}) is None


@pytest.fixture
def plan_settings(tmp_path):
    database = tmp_path / "weekly.db"
    upgrade_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO users(id,age,max_hr,training_days_per_week,marathon_goal_time,running_goal_time) "
                           "VALUES(1,30,190,3,'04:00:00','04:00:00')")
        connection.execute("INSERT INTO users(id,age,max_hr,training_days_per_week,marathon_goal_time,running_goal_time) "
                           "VALUES(2,32,188,3,'04:10:00','04:10:00')")
        for offset in range(35):
            day = START - timedelta(days=34 - offset)
            connection.execute("INSERT INTO health_metrics(user_id,date,resting_hr,hrv,sleep_duration) "
                               "VALUES(1,?,?,?,?)", (day.isoformat(), 55, 50, 7.5))
        for activity_id, duration in enumerate((30, 40, 50), 1):
            connection.execute("INSERT INTO activities(id,user_id,date,type,distance,duration,avg_hr,notes) "
                               "VALUES(?,1,?,'running',5,?,135,'Original athlete note')",
                               (activity_id, (START - timedelta(days=activity_id)).isoformat(), duration))
    return replace(get_settings(), db_path=database, llm_provider="none")


def _activity_bytes(settings):
    with sqlite3.connect(settings.db_path) as connection:
        return connection.execute("SELECT id,user_id,date,type,distance,duration,notes FROM activities ORDER BY id").fetchall()


def test_suggestions_need_individual_approval_and_keep_logged_activities(plan_settings):
    before = _activity_bytes(plan_settings)
    proposal = propose_week(START, settings=plan_settings, today=START)
    assert proposal["status"] == "open"
    assert len(proposal["changes"]) == 3
    assert get_weekly_plan(START, settings=plan_settings)["sessions"] == {}
    known = {fact["id"] for fact in proposal["facts"]}
    assert all(change["reason"] and change["fact_ids"] and set(change["fact_ids"]) <= known
               for change in proposal["changes"])
    facts = {fact["id"]: fact["display"] for fact in proposal["facts"]}
    assert float(facts["MAX_PLAN_LOAD"].split()[0]) <= float(facts["PRIOR_WEEK_LOAD"].split()[0]) * 1.1 + .1
    assert all("MAX_PLAN_LOAD" in change["fact_ids"] for change in proposal["changes"])
    first, second, third = (change["id"] for change in proposal["changes"])
    accepted = accept_change(first, settings=plan_settings)
    assert accepted["revision"] == 1
    assert len(accepted["sessions"]) == 1
    reject_change(second, settings=plan_settings)
    assert get_weekly_plan(START, settings=plan_settings)["revision"] == 1
    accepted = accept_change(third, settings=plan_settings)
    assert accepted["revision"] == 2
    assert len(accepted["sessions"]) == 2
    assert get_proposal(proposal["id"], settings=plan_settings)["status"] == "complete"
    with pytest.raises(ValueError, match="no longer pending"):
        accept_change(first, settings=plan_settings)
    assert _activity_bytes(plan_settings) == before
    with sqlite3.connect(plan_settings.db_path) as connection:
        snapshots = connection.execute("SELECT before_json FROM coach_plan_undo ORDER BY id").fetchall()
        assert json.loads(snapshots[0][0]) == {}
        assert len(json.loads(snapshots[1][0])) == 1
    assert len(undo_last_coach_change(START, settings=plan_settings)["sessions"]) == 1
    with sqlite3.connect(plan_settings.db_path) as connection:
        assert connection.execute("SELECT after_revision,expected_revision FROM coach_plan_undo "
                                  "ORDER BY id").fetchall() == [(1, 3), (2, 2)]
    assert undo_last_coach_change(START, settings=plan_settings)["sessions"] == {}
    undone = get_proposal(proposal["id"], settings=plan_settings)["changes"]
    assert [change["undone"] for change in undone] == [True, False, True]
    with pytest.raises(ValueError, match="No coach change"):
        undo_last_coach_change(START, settings=plan_settings)
    assert _activity_bytes(plan_settings) == before


def test_excluded_and_walking_minutes_do_not_inflate_training_budget(plan_settings):
    with sqlite3.connect(plan_settings.db_path) as connection:
        for activity_id, activity_type, avg_hr in ((20, "meditation", None), (21, "walking", 100)):
            connection.execute("INSERT INTO activities(id,user_id,date,type,distance,duration,avg_hr) "
                               "VALUES(?,1,?,?,0,300,?)",
                               (activity_id, (START - timedelta(days=1)).isoformat(), activity_type, avg_hr))
    proposal = propose_week(START, settings=plan_settings, today=START)
    prior = next(fact for fact in proposal["facts"] if fact["id"] == "PRIOR_WEEK_MINUTES")
    assert prior["display"] == "120 min"


def test_missing_load_blocks_suggestions_and_acceptance_rechecks_load(plan_settings):
    proposal = propose_week(START, settings=plan_settings, today=START)
    with sqlite3.connect(plan_settings.db_path) as connection:
        connection.execute("UPDATE activities SET avg_hr=NULL WHERE user_id=1")
    with pytest.raises(ValueError, match="Recent session load is missing"):
        accept_change(proposal["changes"][0]["id"], settings=plan_settings)
    assert get_weekly_plan(START, settings=plan_settings)["sessions"] == {}
    with pytest.raises(ValueError, match="Recent session load is missing"):
        propose_week(START, settings=plan_settings, today=START)


def test_new_illness_signal_blocks_todays_pending_session(plan_settings, monkeypatch):
    proposal = propose_week(START, settings=plan_settings, today=START)

    class FixtureDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 6, 29, tzinfo=tz)

    monkeypatch.setattr("services.weekly_plan_service.datetime", FixtureDateTime)
    with sqlite3.connect(plan_settings.db_path) as connection:
        connection.execute("UPDATE health_metrics SET resting_hr=70,hrv=30 WHERE date=?", (START.isoformat(),))
    with pytest.raises(ValueError, match="recovery calls for rest"):
        accept_change(proposal["changes"][0]["id"], settings=plan_settings)
    assert get_weekly_plan(START, settings=plan_settings)["sessions"] == {}


def test_revision_with_unknown_gym_load_is_not_proposed(plan_settings):
    proposal = propose_week(START, settings=plan_settings, today=START)
    with pytest.raises(ValueError, match="cannot be verified"):
        revise_proposal(proposal["id"], "Put gym on Thursday", settings=plan_settings)
    with pytest.raises(ValueError, match="Use fixed team training"):
        revise_proposal(proposal["id"], "Put football on Thursday", settings=plan_settings)
    assert get_proposal(proposal["id"], settings=plan_settings)["status"] == "open"


def test_competing_proposals_stale_and_undo_preserves_unrelated_athlete_edits(plan_settings):
    first = propose_week(START, settings=plan_settings, today=START)
    second = propose_week(START, settings=plan_settings, today=START)
    accept_change(first["changes"][0]["id"], settings=plan_settings)
    assert get_proposal(second["id"], settings=plan_settings)["status"] == "stale"
    with pytest.raises(ValueError, match="no longer pending"):
        accept_change(second["changes"][0]["id"], settings=plan_settings)
    set_fixed_commitment(START + timedelta(days=1), "football", settings=plan_settings)
    assert scheduled_team_sports(START + timedelta(days=1), settings=plan_settings) == ("football",)
    restored = undo_last_coach_change(START, settings=plan_settings)
    assert START.isoformat() not in restored["sessions"]
    assert restored["sessions"][(START + timedelta(days=1)).isoformat()]["sport"] == "football"
    set_fixed_commitment(START + timedelta(days=1), None, settings=plan_settings)
    assert scheduled_team_sports(START + timedelta(days=1), settings=plan_settings) == ()


def test_undo_refuses_to_overwrite_athlete_edit_of_same_day(plan_settings):
    proposal = propose_week(START, settings=plan_settings, today=START)
    change = proposal["changes"][0]
    accept_change(change["id"], settings=plan_settings)
    day = date.fromisoformat(change["day"])
    set_fixed_commitment(day, "football", settings=plan_settings)
    with pytest.raises(ValueError, match="This day was edited"):
        undo_last_coach_change(START, settings=plan_settings)
    assert get_weekly_plan(START, settings=plan_settings)["sessions"][day.isoformat()]["sport"] == "football"


def test_revision_creates_fresh_proposal_not_a_plan_edit(plan_settings):
    original = propose_week(START, settings=plan_settings, today=START)
    revised = revise_proposal(original["id"], "Make Saturday a rest day", settings=plan_settings)
    assert revised["id"] != original["id"]
    assert revised["changes"][0]["session"] is None
    assert revised["changes"][0]["fact_ids"] == ["ATHLETE_REQUEST", "PLAN_WEEK_START"]
    assert get_proposal(original["id"], settings=plan_settings)["status"] == "stale"
    assert get_weekly_plan(START, settings=plan_settings)["sessions"] == {}
    with pytest.raises(ValueError, match="stale or complete"):
        revise_proposal(original["id"], "Make Friday a rest day", settings=plan_settings)


def test_user_scope_and_plan_tool_read_only(plan_settings):
    proposed = propose_week(START, settings=plan_settings, today=START)
    change_id = proposed["changes"][0]["id"]
    with pytest.raises(ValueError, match="not found"):
        accept_change(change_id, settings=plan_settings, user_id=2)
    with pytest.raises(ValueError, match="not found"):
        get_proposal(proposed["id"], settings=plan_settings, user_id=2)
    assert get_weekly_plan(START, settings=plan_settings, user_id=2)["sessions"] == {}
    tools = CoachTools(plan_settings.db_path, 1, plan_settings.local_timezone, plan_settings.sleep_goal_hours)
    before = get_weekly_plan(START, settings=plan_settings)
    assert tools.call("plan_week", {"start_date": START.isoformat()})["sessions"] == []
    assert get_weekly_plan(START, settings=plan_settings) == before
    accept_change(change_id, settings=plan_settings)
    result = tools.plan_week(START)
    assert len(result["sessions"]) == 1
    assert any(fact["id"] == "PLAN_DAY_0" for fact in result["facts"])
    other = CoachTools(plan_settings.db_path, 2, plan_settings.local_timezone, plan_settings.sleep_goal_hours)
    assert other.plan_week(START)["sessions"] == []
    with pytest.raises(ValueError, match="Monday"):
        tools.plan_week(START + timedelta(days=1))


def test_accepted_team_commitment_reaches_daily_ranking_and_rest_option(plan_settings):
    set_fixed_commitment(START, "volleyball", settings=plan_settings)
    decision = get_or_create_daily_decision(START, settings=plan_settings)
    if decision.intensity == "rest":
        assert not decision.sports
        assert any(item["sport"] == "volleyball" and "Skip" in item["label"]
                   for item in decision.team_options)
    else:
        assert decision.sports[0]["sport"] == "volleyball"
        assert all(item["sport"] != "volleyball" for item in decision.team_options)
    with sqlite3.connect(plan_settings.db_path) as connection:
        connection.execute("UPDATE health_metrics SET resting_hr=70,hrv=30 WHERE date=?", (START.isoformat(),))
    rest = get_or_create_daily_decision(START, settings=plan_settings)
    assert rest.intensity == "rest"
    assert not rest.sports
    assert any(item["sport"] == "volleyball" and "Skip" in item["label"] for item in rest.team_options)


def test_fixed_commitment_stales_pending_proposals_and_is_never_changed_by_coach(plan_settings):
    proposal = propose_week(START, settings=plan_settings, today=START)
    day = date.fromisoformat(proposal["changes"][0]["day"])
    set_fixed_commitment(day, "football", settings=plan_settings)
    assert list_proposals(START, settings=plan_settings)[0]["status"] == "stale"
    with pytest.raises(ValueError, match="no longer pending"):
        accept_change(proposal["changes"][0]["id"], settings=plan_settings)
    assert get_weekly_plan(START, settings=plan_settings)["sessions"][day.isoformat()]["sport"] == "football"
