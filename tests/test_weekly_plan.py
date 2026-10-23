"""Synthetic plan safety, approval and import tests; no athlete database is used."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from coach.agent import _user_lock
from coach.planning import (
    MOBILITY_NOTE,
    HabitPattern,
    LoadModel,
    WeekDraft,
    WeekNarrative,
    _context,
    apply_draft,
    build_habit_week,
    estimate_load,
    habit_pattern,
    is_hard,
    is_recovery_item,
    load_model,
    propose_daily_conflict,
    propose_opinion_recommendations,
    propose_week,
    revise_week,
    validate_draft,
    validate_narrative,
    validate_week,
    week_load_breakdown,
)
from coach.proposals import (
    apply,
    create_proposal,
    dismiss,
    get_proposal,
    get_week,
    link_activity,
    list_commitments,
    list_proposals,
    list_protected_habits,
    manual_session,
    materialize_week,
    request_revision,
    save_commitment,
    save_protected_habit,
    skip_manual_session,
    undo_last,
)
from coach.tools import CoachTools
from config import get_settings
from db.migration_runner import upgrade_database
from db.repository import bulk_upsert_activities
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


def test_fixed_session_does_not_conflict_with_daily_decision():
    model = LoadModel(100, {("football", "match"): 1}, {"football": 1})
    fixed = {**session(START, sport="football", intent="match", minutes=90),
             "origin": "fixed", "status": "planned"}
    assert validate_week([fixed], model, today=START, decisions={START: "rest"}, week_start=START) == []


def test_week_narrative_needs_one_supported_reason_per_code_change():
    good = WeekNarrative.model_validate({"summary": "A controlled week", "reasons": [
        {"reason": "Keep load at 200.0 TRIMP.", "fact_ids": ["TRAINING_LOAD"]}]})
    assert validate_narrative(good, (change(START),), FACTS) == []
    bad = WeekNarrative.model_validate({"summary": "A controlled week", "reasons": [
        {"reason": "Use 999 bpm.", "fact_ids": ["UNKNOWN"]}]})
    assert "Unknown fact ID" in validate_narrative(bad, (change(START),), FACTS)
    assert "Unsupported number in reason" in validate_narrative(bad, (change(START),), FACTS)


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
    assert scheduled_team_sports(START + timedelta(days=1), settings=replace(get_settings(), db_path=database)) == ()
    save_commitment(database, 1, weekday=2, start_time="18:00", sport="volleyball", kind="training",
                    duration_min=75, active=True, commitment_id=commitment_id)
    moved = get_week(database, 1, START)["sessions"][0]
    assert moved["date"] == (START + timedelta(days=2)).isoformat()
    assert moved["status"] == "planned"


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


def test_manual_skip_retains_row_and_bumps_version(database):
    identifier = manual_session(database, 1, session(START))
    skip_manual_session(database, 1, identifier)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT status FROM plan_sessions WHERE id=?", (identifier,)).fetchone() == (
            "skipped",)
        assert connection.execute("SELECT version FROM plan_versions WHERE user_id=1").fetchone() == (2,)
    with pytest.raises(ValueError, match="unlogged"):
        skip_manual_session(database, 1, identifier)


def test_approved_remove_is_a_reversible_skip(database):
    identifier = manual_session(database, 1, session(START))
    proposal = create_proposal(database, 1, "change", "Rest instead", FACTS,
                               [change(START, action="remove", identifier=identifier)])
    apply(database, 1, proposal["id"], [proposal["changes"][0]["id"]])
    assert get_week(database, 1, START)["sessions"][0]["status"] == "skipped"
    undo_last(database, 1)
    assert get_week(database, 1, START)["sessions"][0]["status"] == "planned"


def test_csv_and_sync_repository_upsert_link_matching_plan(database):
    session_id = manual_session(database, 1, session(START))
    second_id = manual_session(database, 1, session(START))
    engine = create_engine(f"sqlite:///{database}")
    try:
        with Session(engine) as db_session:
            assert bulk_upsert_activities(db_session, [{"user_id": 1, "date": START, "type": "running",
                                                        "distance": 5.0, "duration": 30.0, "avg_hr": 135.0,
                                                        "external_id": "invented-sync-1"}]) == 1
            db_session.commit()
        with Session(engine) as db_session:
            assert bulk_upsert_activities(db_session, [{"user_id": 1, "date": START, "type": "running",
                                                        "distance": 5.0, "duration": 30.0, "avg_hr": 135.0,
                                                        "external_id": "invented-sync-1"}]) == 0
            db_session.commit()
        with sqlite3.connect(database) as connection:
            row = connection.execute("SELECT status,linked_activity_id FROM plan_sessions WHERE id=?",
                                     (session_id,)).fetchone()
            assert row[0] == "done" and row[1] is not None
            assert connection.execute("SELECT status,linked_activity_id FROM plan_sessions WHERE id=?",
                                      (second_id,)).fetchone() == ("planned", None)
            assert connection.execute("SELECT version FROM plan_versions WHERE user_id=1").fetchone()[0] == 3
    finally:
        engine.dispose()


def test_proposal_rejects_unknown_facts_and_unsupported_numbers(database):
    invalid = change(START)
    invalid["fact_ids"] = ["UNKNOWN"]
    with pytest.raises(ValueError, match="known facts"):
        create_proposal(database, 1, "change", "Invalid", FACTS, [invalid])
    invalid["fact_ids"] = ["TRAINING_LOAD"]
    invalid["reason"] = "Run 123 minutes."
    with pytest.raises(ValueError, match="absent"):
        create_proposal(database, 1, "change", "Invalid", FACTS, [invalid])


def test_mocked_llm_week_draft_is_validated_and_never_applied(database):
    class FakeLLM:
        def __init__(self):
            self.calls = 0

        def generate_json(self, system, prompt, response_schema):
            self.calls += 1
            assert response_schema.__name__ == "WeekNarrative"
            import json
            count = len(json.loads(prompt)["code_built_changes"])
            return {"summary": "Easy week", "reasons": [
                {"reason": "Keep the week controlled.", "fact_ids": ["LOAD_BASE"]} for _ in range(count)]}

    settings = replace(get_settings(), db_path=database, llm_provider="none")
    llm = FakeLLM()
    proposal = propose_week(START, settings=settings, llm=llm, today=START - timedelta(days=3))
    assert llm.calls == 1
    assert proposal["status"] == "pending"
    assert get_week(database, 1, START)["sessions"] == []
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM coach_llm_calls").fetchone()[0] == 1
    with _user_lock(database, 1), pytest.raises(RuntimeError, match="already running"):
        propose_week(START, settings=settings, llm=llm, today=START - timedelta(days=3))
    with pytest.raises(RuntimeError, match="call limit"):
        propose_week(START, settings=replace(settings, coach_daily_call_limit=1), llm=llm,
                     today=START - timedelta(days=3))


def test_plain_word_revision_uses_model_but_does_not_apply(database):
    class FakeLLM:
        def __init__(self):
            self.day = START

        def generate_json(self, system, prompt, response_schema):
            item = change(self.day)
            item["fact_ids"] = ["LOAD_BASE"]
            return {"summary": "Revised week", "changes": [item]}

    settings = replace(get_settings(), db_path=database, llm_provider="none")
    llm = FakeLLM()
    original = propose_week(START, settings=settings, llm=llm, today=START - timedelta(days=3))
    llm.day = START + timedelta(days=2)
    revised = revise_week(original["id"], "Please put my easy run on Wednesday", settings=settings,
                          llm=llm, today=START - timedelta(days=3))
    assert get_proposal(database, 1, original["id"])["status"] == "superseded"
    assert revised["status"] == "pending"
    assert revised["changes"][0]["session"]["date"] == llm.day.isoformat()
    assert get_week(database, 1, START)["sessions"] == []


def test_long_easy_run_is_optional_when_cap_does_not_fit():
    model = LoadModel(100, {("running", "easy"): 1}, {"running": 1})
    draft = WeekDraft.model_validate({"summary": "Easy week", "changes": [change(START)]})
    errors = validate_draft(draft, [], FACTS, model, START, START - timedelta(days=7), {}, True)
    assert errors == []
    draft = WeekDraft.model_validate({"summary": "Long run", "changes": [change(START, minutes=60)]})
    assert validate_draft(draft, [], FACTS, model, START, START - timedelta(days=7), {}, True) == []


def test_habit_pattern_uses_four_week_medians():
    rows = []
    for week, count in enumerate((1, 2, 2, 3)):
        rows.extend({"date": (START - timedelta(days=28 - 7 * week - n)).isoformat(),
                     "sport": "running", "duration_min": 40} for n in range(count))
    rows.append({"date": START.isoformat(), "sport": "gym", "duration_min": 200})
    rows.append({"date": (START - timedelta(days=4)).isoformat(), "sport": "volleyball", "duration_min": 90})
    pattern = habit_pattern(rows, START)
    assert pattern.sessions_per_week == {"running": 2, "gym": 0}
    assert pattern.duration_min["running"] == 40


def test_builder_keeps_fixed_match_and_trims_flexible_first():
    fixed = {**session(START + timedelta(days=5), sport="football", intent="match", minutes=90),
             "origin": "fixed", "status": "planned"}
    gym = {**session(START + timedelta(days=2), sport="gym", intent="light", minutes=40, identifier=7),
           "origin": "athlete", "status": "planned"}
    model = LoadModel(120, {("football", "match"): 1, ("gym", "light"): 1,
                            ("running", "easy"): 1}, {"football": 1, "gym": 1, "running": 1})
    result = build_habit_week([fixed, gym], model, HabitPattern({"running": 1, "gym": 1},
                                {"running": 60, "gym": 40}), START, START - timedelta(days=7), {}, True, 135)
    assert not result.warnings
    assert next(item for item in result.candidate if item["origin"] == "fixed") == fixed
    assert any(item["sport"] == "running" and item["duration_min"] < 60 for item in result.candidate)
    assert "shorter" in result.summary
    preview = week_load_breakdown(list(result.candidate), model, START)
    assert preview["weekly_total"] <= preview["cap"]
    assert len(preview["days"]) == 7 and any(item["rest"] for item in preview["days"])
    assert all(change["session"]["sport"] != "football" for change in result.changes)


def test_builder_abstains_when_fixed_commitments_exceed_cap():
    fixed = [{**session(START + timedelta(days=day), sport="football", intent="match", minutes=90),
              "origin": "fixed", "status": "planned"} for day in (1, 5)]
    model = LoadModel(100, {("football", "match"): 1}, {"football": 1})
    result = build_habit_week(fixed, model, HabitPattern({"running": 0, "gym": 0},
                              {"running": 30, "gym": 30}), START, START - timedelta(days=7), {}, False, None)
    assert all(item["origin"] == "fixed" for item in result.candidate if item["sport"] == "football")
    assert all(item["session"]["notes"] == MOBILITY_NOTE for item in result.changes)
    assert any("exceed" in warning for warning in result.warnings)
    assert "Lighter week" in result.summary


def test_protected_habits_use_nonteam_days_and_are_immutable(database):
    save_commitment(database, 1, weekday=1, start_time="19:00", sport="volleyball",
                    kind="training", duration_min=90)
    save_commitment(database, 1, weekday=5, start_time="15:00", sport="football",
                    kind="match", duration_min=90)
    habit_id = save_protected_habit(database, 1, sport="gym", intent="light upper body",
                                    duration_min=30, per_week=2)
    assert list_protected_habits(database, 1)[0]["id"] == habit_id
    week = get_week(database, 1, START)["sessions"]
    protected = [item for item in week if item["origin"] == "protected"]
    assert len(protected) == 2
    assert len({item["date"] for item in protected}) == 2
    assert not {item["date"] for item in protected} & {
        item["date"] for item in week if item["origin"] == "fixed"}
    assert all(item["duration_min"] == 30 for item in protected)
    assert get_week(database, 1, START)["sessions"] == week
    identified = {**protected[0], "id": 123}
    with pytest.raises(ValueError, match="Protected habits"):
        apply_draft([identified], [{"change_type": "remove", "session": identified}])
    with pytest.raises(ValueError, match="seven"):
        save_protected_habit(database, 1, sport="running", intent="easy", duration_min=30, per_week=6)
    save_protected_habit(database, 1, sport="gym", intent="light upper body", duration_min=30,
                         per_week=2, active=False, habit_id=habit_id)
    assert not any(item["origin"] == "protected" for item in get_week(database, 1, START)["sessions"])


def test_protected_and_walking_load_are_kept_above_cap():
    fixed = {**session(START + timedelta(days=1), sport="volleyball", intent="training", minutes=90),
             "origin": "fixed", "status": "planned"}
    protected = {**session(START + timedelta(days=2), sport="gym", intent="light upper body", minutes=30),
                 "origin": "protected", "status": "planned"}
    model = LoadModel(80, {("volleyball", "training"): 1},
                      {"volleyball": 1, "gym": 1}, expected_walking_weekly=12)
    result = build_habit_week([fixed, protected], model,
                              HabitPattern({"running": 0, "gym": 0}, {"running": 30, "gym": 30}),
                              START, START - timedelta(days=7), {}, False, None, 1.4)
    assert fixed in result.candidate and protected in result.candidate
    assert "1.40" in result.summary
    assert result.changes and all(is_recovery_item(item["session"]) for item in result.changes)
    preview = week_load_breakdown(list(result.candidate), model, START)
    assert preview["weekly_total"] == 132
    assert preview["cap"] == 88
    assert preview["expected_walking_weekly"] == 12
    assert any(day["rest"] and day["estimated_load"] > 0 for day in preview["days"])
    assert validate_week(list(result.candidate), model, today=START - timedelta(days=7),
                         decisions={}, week_start=START) == []


def test_flexible_session_dropped_for_cap_becomes_lighter_week():
    fixed = {**session(START + timedelta(days=5), sport="football", intent="match", minutes=90),
             "origin": "fixed", "status": "planned"}
    model = LoadModel(90, {("football", "match"): 1, ("running", "easy"): 1},
                      {"football": 1, "running": 1})
    result = build_habit_week([fixed], model, HabitPattern({"running": 1, "gym": 0},
                              {"running": 30, "gym": 30}), START, START - timedelta(days=7),
                              {}, False, 130, 1.35)
    assert result.status == "proposal"
    assert "Lighter week" in result.summary and "1.35" in result.summary
    assert any("dropped" in warning for warning in result.warnings)
    assert all(is_recovery_item(change["session"]) for change in result.changes)
    assert all(change["fact_ids"] == ["LOAD_RATIO", "LOAD_CAP"] for change in result.changes)
    assert week_load_breakdown(list(result.candidate), model, START)["weekly_total"] <= model.cap


def test_observed_walking_enters_base_and_proposed_total_equally(database):
    settings = replace(get_settings(), db_path=database)
    before = load_model(database, 1, START, settings)
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO activities(user_id,date,type,distance,duration,avg_hr) "
                           "VALUES(1,?,'walking',3,30,100)", ((START - timedelta(days=3)).isoformat(),))
    after = load_model(database, 1, START, settings)
    walking_delta = after.expected_walking_weekly - before.expected_walking_weekly
    assert walking_delta > 0
    assert after.previous_weekly_average - before.previous_weekly_average == pytest.approx(walking_delta)
    empty_week = week_load_breakdown([], after, START)
    assert empty_week["weekly_total"] == pytest.approx(after.expected_walking_weekly)
    assert all(day["rest"] for day in empty_week["days"])


def test_no_safe_change_only_when_no_day_available_for_recovery():
    fixed = [{**session(START + timedelta(days=day), sport="football", intent="match", minutes=90),
              "origin": "fixed", "status": "planned"} for day in range(7)]
    model = LoadModel(100, {("football", "match"): 1}, {"football": 1})
    result = build_habit_week(fixed, model, HabitPattern({"running": 0, "gym": 0},
                              {"running": 30, "gym": 30}), START, START - timedelta(days=7), {}, False, None)
    assert result.changes == ()
    assert result.summary and result.warnings
    assert result.status == "no_safe_change"
    already = build_habit_week([], LoadModel(100, {}, {}),
                               HabitPattern({"running": 0, "gym": 0}, {"running": 30, "gym": 30}),
                               START, START - timedelta(days=7), {}, False, None)
    assert already.status == "already_planned"


def test_projected_protected_facts_have_unique_ids_and_sources(database):
    save_protected_habit(database, 1, sport="gym", intent="light upper body", duration_min=30, per_week=2)
    settings = replace(get_settings(), db_path=database, llm_provider="none")
    _, facts, *_ = _context(database, 1, START, settings, START - timedelta(days=7))
    protected = [fact for fact in facts if fact["id"].startswith("PLAN_PROTECTED_")]
    assert len(protected) == 4
    assert len({fact["id"] for fact in protected}) == 4
    assert {fact["source"] for fact in protected} == {"protected_habits", "protected_habits.duration_min"}


def test_approved_mobility_does_not_remove_over_cap_protected_habit(database, monkeypatch):
    save_commitment(database, 1, weekday=1, start_time="19:00", sport="volleyball",
                    kind="training", duration_min=90)
    save_protected_habit(database, 1, sport="gym", intent="light upper body", duration_min=30, per_week=2)
    model = LoadModel(80, {("volleyball", "training"): 1},
                      {"volleyball": 1, "gym": 1}, expected_walking_weekly=12)
    monkeypatch.setattr("coach.planning.load_model", lambda *args: model)
    day = START + timedelta(days=3)
    mobility = {**session(day, sport="gym", intent="recovery", minutes=15), "notes": MOBILITY_NOTE}
    facts = [{"id": "LOAD_CAP", "metric": "Cap", "display": "88.0 TRIMP", "source": "metrics"}]
    proposal = create_proposal(database, 1, "weekly_plan", "Lighter week", facts,
                               [{"change_type": "add", "session": mobility,
                                 "reason": "This is non-training mobility.", "fact_ids": ["LOAD_CAP"]}])
    applied = apply(database, 1, proposal["id"], [proposal["changes"][0]["id"]])
    assert applied["status"] == "applied"
    week = get_week(database, 1, START)["sessions"]
    assert len([item for item in week if item["origin"] == "protected"]) == 2
    assert len([item for item in week if item["origin"] == "fixed"]) == 1
    assert any(is_recovery_item(item) for item in week)


def test_group_is_atomic_and_unsafe_selected_set_writes_nothing(database):
    grouped = [change(START), change(START + timedelta(days=2))]
    for item in grouped:
        item["group_id"] = "capacity"
    proposal = create_proposal(database, 1, "weekly_plan", "Together", FACTS, grouped)
    before = get_week(database, 1, START)
    with pytest.raises(ValueError, match="group together"):
        apply(database, 1, proposal["id"], [proposal["changes"][0]["id"]])
    assert get_week(database, 1, START) == before
    assert get_proposal(database, 1, proposal["id"])["status"] == "pending"
    apply(database, 1, proposal["id"], [item["id"] for item in proposal["changes"]])
    assert len(get_week(database, 1, START)["sessions"]) == 2

    hard = create_proposal(database, 1, "weekly_plan", "Unsafe", FACTS, [
        change(START + timedelta(days=1), sport="football", intent="match", minutes=90),
        change(START + timedelta(days=2), sport="volleyball", intent="training", minutes=90)])
    before = get_week(database, 1, START)
    with pytest.raises(ValueError, match="Unsafe plan change"):
        apply(database, 1, hard["id"], [item["id"] for item in hard["changes"]])
    assert get_week(database, 1, START) == before
    assert get_proposal(database, 1, hard["id"])["status"] == "pending"


def test_opinion_recommendation_and_daily_conflict_only_create_proposals(database, monkeypatch):
    settings = replace(get_settings(), db_path=database, llm_provider="none")
    monkeypatch.setattr("coach.planning.load_model", lambda *args: LoadModel(100, {("running", "easy"): 1},
                                                                              {"running": 1}))
    recommendation = {"action": "add_to_plan", "text": "Keep this controlled at 130 bpm.",
                      "session": {"sport": "running", "intent": "easy", "duration_min": 30,
                                  "hr_cap_bpm": 130}}
    facts = [{"id": "HR_CAP", "metric": "HR cap", "display": "130 bpm", "source": "user.hr_zones"}]
    proposals = propose_opinion_recommendations(99, START - timedelta(days=1), [recommendation], facts,
                                                 settings=settings, today=START - timedelta(days=1))
    assert len(proposals) == 1 and len(proposals[0]["changes"]) == 1
    assert get_week(database, 1, START)["sessions"] == []
    tempo_id = manual_session(database, 1, session(START + timedelta(days=1), intent="tempo"))
    decision_facts = [{"id": "READINESS", "metric": "Readiness", "display": "70", "source": "metrics"}]
    daily = propose_daily_conflict(START + timedelta(days=1), "easy", decision_facts, settings=settings)
    assert len(daily) == 1
    assert daily[0]["changes"][0]["session"]["id"] == tempo_id
    assert daily[0]["changes"][0]["session"]["intent"] == "easy"
    assert propose_daily_conflict(START + timedelta(days=1), "easy", decision_facts, settings=settings) == []
    dismiss(database, 1, daily[0]["id"])
    assert propose_daily_conflict(START + timedelta(days=1), "easy", decision_facts, settings=settings) == []
