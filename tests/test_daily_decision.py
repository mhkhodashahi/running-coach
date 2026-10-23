"""Invented fixture tests for daily decision rules, explanation and storage."""

import json
import sqlite3
from dataclasses import replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from coach.decision import (
    PriorSession,
    decide_intensity,
    is_hard_session,
    provisional_day,
    rank_sports,
    session_cause,
    team_options,
)
from config import get_settings
from db.migration_runner import upgrade_database
from services.daily_decision_service import (
    build_daily_decision,
    explain_decision,
    fallback_explanation,
    get_or_create_daily_decision,
    set_athlete_choice,
)

DAY = date(2026, 6, 29)
NOW = datetime(2026, 6, 30, tzinfo=ZoneInfo("Europe/Berlin"))


def session(hours_ago, sport="running", intent=None, z4=None):
    return PriorSession(NOW - timedelta(hours=hours_ago), sport, intent, z4)


@pytest.mark.parametrize("illness,readiness,ratio,sessions,expected", [
    (True, 90, 1, (), "illness_signal"),
    (False, 29.99, 1, (), "readiness_below_30"),
    (False, 30, 1, (), "readiness_below_50"),
    (False, None, 1, (), "not_enough_data"),
    (False, 50, 1.5001, (), "load_ratio_above_1_5"),
    (False, 70, 1.5, (), "load_ratio_above_1_3"),
    (False, 70, 1.3, (), "hard_allowed"),
    (False, 70, 1.3001, (), "load_ratio_above_1_3"),
    (False, 70, 1.3, (session(1, "football"),), "hard_in_last_48h"),
    (False, 70, 1.3, (session(49, "football"),), "hard_allowed"),
    (False, 69.99, 1, (), "otherwise_easy"),
])
def test_intensity_first_match_and_boundaries(illness, readiness, ratio, sessions, expected):
    result = decide_intensity(illness, readiness, ratio, sessions, NOW)
    assert result.rule == expected
    assert result.intensity == ("rest" if expected.startswith(("illness", "readiness_below_30")) else
                                "hard" if expected == "hard_allowed" else "easy")
    assert result.fact_ids


def test_hard_session_detection():
    assert is_hard_session(session(1, intent="tempo"))
    assert is_hard_session(session(1, intent="race"))
    assert is_hard_session(session(1, z4=15))
    assert is_hard_session(session(1, sport="volleyball"))
    assert not is_hard_session(session(1, z4=14.99))


def test_session_cause_names_recorded_sport_and_date_without_inventing_a_match():
    team = PriorSession(datetime(2026, 10, 17, tzinfo=ZoneInfo("Europe/Berlin")), "football")
    tempo = PriorSession(team.when, "running", "tempo")
    assert session_cause(team) == "football session on Sat 17 Oct"
    assert session_cause(tempo) == "tempo run on Sat 17 Oct"


def test_sport_ranking_and_rest_option():
    assert rank_sports("rest", (), NOW, 130) == ()
    ranked = rank_sports("easy", (session(2, "football"), session(4, "running")), NOW, 130)
    assert {item.sport for item in ranked} == {"running", "gym"}
    assert [item.rank for item in ranked] == [1, 2]
    assert ranked[0].sport == "gym"
    assert next(item for item in ranked if item.sport == "running").session["hr_cap_bpm"] == 130
    assert all(item.session["hr_cap_bpm"] is None or isinstance(item.session["hr_cap_bpm"], int)
               for item in ranked)
    assert team_options("easy") == ({"sport": "football", "label": "Only with team training today"},
                                    {"sport": "volleyball", "label": "Only with team training today"})


def test_three_day_count_precedes_seven_day_tiebreaker():
    history = (session(50, "running"), session(60, "running"), session(70, "gym"))
    ranked = rank_sports("easy", history, NOW, 132)
    assert [item.sport for item in ranked] == ["gym", "running"]
    assert "last 3 days" in ranked[0].reason
    tie_3d = (session(50, "running"), session(60, "gym"), session(100, "running"))
    assert rank_sports("easy", tie_3d, NOW, 132)[0].sport == "gym"


def test_easy_duration_and_committed_team_priority():
    short = rank_sports("easy", (), NOW, 130, readiness=69.99)
    long = rank_sports("easy", (), NOW, 130, readiness=70)
    assert {item.session["duration_min"] for item in short} == {30}
    assert {item.session["duration_min"] for item in long} == {45}
    hard = rank_sports("hard", (), NOW, 130, readiness=90)
    assert next(item.session["duration_min"] for item in hard if item.sport == "running") == 40
    assert next(item.session["duration_min"] for item in hard if item.sport == "gym") == 30
    committed = rank_sports("easy", (), NOW, 130, readiness=75, team_commitments=("football",))
    assert [item.sport for item in committed] == ["football", "running", "gym"]
    assert committed[0].session["intent"] == "skills only, no match play"
    assert committed[0].session["hr_cap_bpm"] is None
    assert team_options("easy", ("football",)) == (
        {"sport": "volleyball", "label": "Only with team training today"},)
    assert team_options("rest", ("football",))[0]["label"] == "Skip team training or attend skills only"
    assert rank_sports("rest", (), NOW, 130, team_commitments=("football",)) == ()


def test_provisional_requires_complete_health_day():
    assert provisional_day(DAY, ((DAY, 7.5, None), (DAY - timedelta(days=1), 7, 50))) == (
        DAY - timedelta(days=1), True)
    assert provisional_day(DAY, ((DAY, 7.5, 50),)) == (DAY, False)
    assert provisional_day(DAY, ()) == (DAY, True)
    assert provisional_day(DAY, ((DAY, None, 50), (DAY - timedelta(days=1), 7, 50))) == (
        DAY - timedelta(days=1), True)


@pytest.fixture
def decision_db(tmp_path):
    database = tmp_path / "decision.db"
    upgrade_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO users(id,max_hr,age,marathon_goal_time,running_goal_time) "
                           "VALUES(1,190,30,'04:00:00','04:00:00')")
        for offset in range(35):
            day = DAY - timedelta(days=34 - offset)
            connection.execute("INSERT INTO health_metrics(user_id,date,resting_hr,hrv,sleep_duration) "
                               "VALUES(1,?,?,?,?)", (day.isoformat(), 55, 50, 7.5))
    return database


def test_builder_uses_latest_complete_day_and_no_future_health(decision_db):
    with sqlite3.connect(decision_db) as connection:
        connection.execute("UPDATE health_metrics SET hrv=NULL WHERE date=?", (DAY.isoformat(),))
        connection.execute("INSERT INTO health_metrics(user_id,date,resting_hr,hrv,sleep_duration) "
                           "VALUES(1,?,?,?,?)", ((DAY + timedelta(days=1)).isoformat(), 100, 100, 12))
    result = build_daily_decision(DAY, decision_db, 1, "Europe/Berlin", 7.5)
    assert result.provisional
    assert result.based_on == (DAY - timedelta(days=1)).isoformat()
    assert result.readiness is not None
    assert {item["sport"] for item in result.sports} == {"running", "gym"} or result.intensity == "rest"
    assert result.last_sync_time == "never synced"


def test_builder_team_commitment_and_readable_boolean_facts(decision_db):
    with sqlite3.connect(decision_db) as connection:
        connection.execute("INSERT INTO activities (id,user_id,date,type,distance,duration,avg_hr) "
                           "VALUES (1,1,?,'football',3,60,140)", (DAY.isoformat(),))
    result = build_daily_decision(DAY, decision_db, 1, "Europe/Berlin", 7.5,
                                  team_commitments=("volleyball",))
    facts = {fact["id"]: fact["display"] for fact in result.facts}
    assert facts["HARD_LAST_48H"] == "football session on Mon 29 Jun"
    assert facts["SPORT_FOOTBALL_LAST_24H"] == "football session on Mon 29 Jun"
    assert facts["TEAM_LAST_48H"] == "football session on Mon 29 Jun"
    assert facts["TEAM_VOLLEYBALL_TODAY"] == "volleyball training planned today"
    assert facts["ILLNESS_FLAG"] == "no combined illness signal"
    if result.intensity == "rest":
        assert not result.sports
        assert any("Skip" in item["label"] for item in result.team_options if item["sport"] == "volleyball")
    else:
        assert result.sports[0]["sport"] == "volleyball"
        assert all(item["sport"] != "volleyball" for item in result.team_options)


def test_planned_team_session_uses_same_priority_as_fixed_commitment(decision_db):
    result = build_daily_decision(DAY, decision_db, 1, "Europe/Berlin", 7.5,
                                  team_commitments=("football",),
                                  planned_team_sessions=("football", "volleyball", "running"))
    facts = {fact["id"]: fact["display"] for fact in result.facts}
    assert facts["TEAM_FOOTBALL_TODAY"] == "football training planned today"
    assert facts["TEAM_VOLLEYBALL_TODAY"] == "volleyball training planned today"
    if result.intensity == "rest":
        assert not result.sports
        assert {item["sport"] for item in result.team_options} == {"football", "volleyball"}
        assert all("Skip" in item["label"] for item in result.team_options)
    else:
        assert [item["sport"] for item in result.sports[:2]] == ["football", "volleyball"]
        assert not result.team_options


def test_running_cap_uses_custom_second_zone_or_exclusive_default(decision_db):
    default = build_daily_decision(DAY, decision_db, 1, "Europe/Berlin", 7.5)
    custom = build_daily_decision(DAY, decision_db, 1, "Europe/Berlin", 7.5,
                                  (("Recovery", 95, 115), ("Easy", 116, 137), ("Steady", 138, 152)))
    if default.intensity != "rest":
        default_run = next(item for item in default.sports if item["sport"] == "running")
        custom_run = next(item for item in custom.sports if item["sport"] == "running")
        assert default_run["session"]["hr_cap_bpm"] == 132
        assert custom_run["session"]["hr_cap_bpm"] == 137


def test_llm_failure_falls_back_and_cannot_change_intensity(decision_db):
    class InvalidModel:
        calls = 0

        def generate_json(self, *args, **kwargs):
            self.calls += 1
            return {"headline": "Go hard", "explanation": "Train at 999 bpm.",
                    "evidence_ids": ["READINESS"], "follow_ups": ["Why?"]}

    original = build_daily_decision(DAY, decision_db, 1, "Europe/Berlin", 7.5)
    model = InvalidModel()
    errors = []
    result = explain_decision(original, model, on_error=lambda attempt, error: errors.append((attempt, error)))
    assert model.calls == 2
    assert [attempt for attempt, _ in errors] == [1, 2]
    assert all("ValidationError" in error or "ValueError" in error for _, error in errors)
    assert result.intensity == original.intensity
    assert result.sports == original.sports
    assert "999" not in result.explanation
    assert result.explanation_source == "fallback"


@pytest.mark.parametrize("rule,phrase", [
    ("illness_signal", "resting HR and HRV both point to strain"),
    ("readiness_below_30", "recovery takes priority"),
    ("not_enough_data", "not enough recovery data"),
    ("readiness_below_50", "protect recovery"),
    ("load_ratio_above_1_5", "training load is well above"),
    ("load_ratio_above_1_3", "above the range for a hard session"),
    ("hard_allowed", "hard session is available"),
    ("hard_in_last_48h", "hard session in the last 48 hours"),
    ("otherwise_easy", "conditions for a hard session"),
])
def test_natural_fallback_for_each_rule(decision_db, rule, phrase):
    original = build_daily_decision(DAY, decision_db, 1, "Europe/Berlin", 7.5)
    text = fallback_explanation(replace(original, rule=rule))
    assert phrase in text
    assert rule not in text
    assert "_" not in text
    assert "1_5" not in text


def test_valid_explanation_cites_facts_but_cannot_change_code_decision(decision_db):
    class Model:
        def generate_json(self, system, prompt, response_schema=None):
            assert "never change" in system
            context = json.loads(prompt.splitlines()[0])
            assert "ranking" not in context
            assert context["top_sport"] in ("running", "gym")
            facts = {fact["id"]: fact["display"] for fact in context["facts"]}
            assert "ILLNESS_FLAG" not in facts
            return {"headline": "Keep it steady.",
                    "explanation": f"I see readiness {facts['READINESS']} and load ratio {facts['LOAD_RATIO']}. "
                                   "I would keep the code decision.",
                    "evidence_ids": ["READINESS", "LOAD_RATIO"],
                    "follow_ups": ["How was my recovery?", "What changed in my load?"]}

    original = build_daily_decision(DAY, decision_db, 1, "Europe/Berlin", 7.5)
    result = explain_decision(original, Model())
    assert result.headline == "Keep it steady."
    assert result.intensity == original.intensity
    assert result.sports == original.sports
    assert result.evidence_ids == ("READINESS", "LOAD_RATIO")
    assert result.explanation_source == "llm"


def test_illness_fact_is_sent_only_when_true(decision_db):
    class Model:
        def generate_json(self, system, prompt, response_schema=None):
            facts = {fact["id"]: fact["display"] for fact in json.loads(prompt.splitlines()[0])["facts"]}
            assert facts["ILLNESS_FLAG"] == "resting HR and HRV signal strain"
            return {"headline": "Rest today.",
                    "explanation": f"I see {facts['ILLNESS_FLAG']}. Readiness is {facts['READINESS']}.",
                    "evidence_ids": ["ILLNESS_FLAG", "READINESS"],
                    "follow_ups": ["How is my recovery?", "What changed in my load?"]}

    original = build_daily_decision(DAY, decision_db, 1, "Europe/Berlin", 7.5)
    illness_facts = tuple({**fact, "display": "resting HR and HRV signal strain"}
                          if fact["id"] == "ILLNESS_FLAG" else fact for fact in original.facts)
    result = explain_decision(replace(original, rule="illness_signal", facts=illness_facts), Model())
    assert result.explanation_source == "llm"


@pytest.mark.parametrize("question", ["Should I train harder?", "Should I train harder."])
def test_question_in_explanation_retries_then_uses_statements(decision_db, question):
    class Model:
        calls = 0

        def generate_json(self, system, prompt, response_schema=None):
            self.calls += 1
            facts = {fact["id"]: fact["display"] for fact in json.loads(prompt.splitlines()[0])["facts"]}
            sentence = question if self.calls == 1 else "Keep the effort easy."
            return {"headline": "Keep it easy.",
                    "explanation": f"I see {facts['READINESS']} readiness and {facts['LOAD_RATIO']} load. {sentence}",
                    "evidence_ids": ["READINESS", "LOAD_RATIO"],
                    "follow_ups": ["How is my recovery?", "What changed in my load?"]}

    model = Model()
    errors = []
    result = explain_decision(build_daily_decision(DAY, decision_db, 1, "Europe/Berlin", 7.5), model,
                              on_error=lambda attempt, error: errors.append(error))
    assert model.calls == 2
    assert "put questions in follow_ups" in errors[0]
    assert result.explanation_source == "llm"
    assert "?" not in result.explanation


def test_explanation_retries_diagnosis_and_missing_second_citation(decision_db):
    class Model:
        calls = 0

        def generate_json(self, system, prompt, response_schema=None):
            self.calls += 1
            context = json.loads(prompt.splitlines()[0])
            facts = {fact["id"]: fact["display"] for fact in context["facts"]}
            if self.calls == 1:
                return {"headline": "Rest.", "explanation": "You have flu. Rest now.",
                        "evidence_ids": ["READINESS"], "follow_ups": ["How is my recovery?", "What is my load?"]}
            return {"headline": "Go easy.",
                    "explanation": f"I see {facts['READINESS']} readiness. Load is {facts['LOAD_RATIO']}.",
                    "evidence_ids": ["READINESS", "LOAD_RATIO"],
                    "follow_ups": ["How is my recovery?", "What is my load?"]}

    model = Model()
    result = explain_decision(build_daily_decision(DAY, decision_db, 1, "Europe/Berlin", 7.5), model)
    assert model.calls == 2
    assert result.headline == "Go easy."


def test_explanation_can_name_ranking_windows_from_fact_pack(decision_db):
    class Model:
        def generate_json(self, system, prompt, response_schema=None):
            facts = {fact["id"]: fact["display"] for fact in json.loads(prompt.splitlines()[0])["facts"]}
            return {"headline": "Keep it easy.",
                    "explanation": (f"Readiness is {facts['READINESS']} and load ratio is {facts['LOAD_RATIO']}. "
                                    "Your running count over 3 days supports the ranking."),
                    "evidence_ids": ["READINESS", "LOAD_RATIO", "SPORT_RECOVERY_WINDOW"],
                    "follow_ups": ["How is recovery?", "What changed in my load?"]}

    result = explain_decision(build_daily_decision(DAY, decision_db, 1, "Europe/Berlin", 7.5), Model())
    assert result.explanation_source == "llm"


def test_retry_names_the_unsupported_number(decision_db):
    class Model:
        prompts = []

        def generate_json(self, system, prompt, response_schema=None):
            self.prompts.append(prompt)
            facts = {fact["id"]: fact["display"] for fact in json.loads(prompt.splitlines()[0])["facts"]}
            explanation = (f"Readiness is {facts['READINESS']} and load ratio is {facts['LOAD_RATIO']}. "
                           + ("Train for 99 minutes." if len(self.prompts) == 1 else "Keep the session easy."))
            return {"headline": "Keep it easy.", "explanation": explanation,
                    "evidence_ids": ["READINESS", "LOAD_RATIO"],
                    "follow_ups": ["How is recovery?", "What is my load?"]}

    model = Model()
    result = explain_decision(build_daily_decision(DAY, decision_db, 1, "Europe/Berlin", 7.5), model)
    assert result.explanation_source == "llm"
    assert "Unsupported numbers: 99" in model.prompts[1]


def test_override_is_separate_and_recomputed_decision_preserves_it(decision_db):
    settings = replace(get_settings(), db_path=decision_db, llm_provider="none")
    first = get_or_create_daily_decision(DAY, settings=settings)
    assert first.athlete_choice is None
    chosen = set_athlete_choice(DAY, "hard", settings=settings)
    assert chosen.athlete_choice == "hard"
    assert chosen.intensity == first.intensity
    with sqlite3.connect(decision_db) as connection:
        row = connection.execute("SELECT payload_json FROM coaching_decisions WHERE decision_type='daily_v2'").fetchone()
        payload = json.loads(row[0])
        assert payload["athlete_choice"] == "hard"
        assert payload["decision"]["intensity"] == first.intensity
        connection.execute("UPDATE health_metrics SET hrv=55 WHERE date=?", (DAY.isoformat(),))
    refreshed = get_or_create_daily_decision(DAY, settings=settings)
    assert refreshed.athlete_choice == "hard"
    assert refreshed.intensity in ("rest", "easy", "hard")
    cleared = set_athlete_choice(DAY, None, settings=settings)
    assert cleared.athlete_choice is None
    with sqlite3.connect(decision_db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM coaching_decisions WHERE decision_type='daily_v2'").fetchone()[0] == 2


def test_new_health_recomputes_provisional_decision(decision_db):
    settings = replace(get_settings(), db_path=decision_db, llm_provider="none")
    with sqlite3.connect(decision_db) as connection:
        connection.execute("UPDATE health_metrics SET sleep_duration=NULL WHERE date=?", (DAY.isoformat(),))
    first = get_or_create_daily_decision(DAY, settings=settings)
    assert first.provisional
    assert first.based_on == (DAY - timedelta(days=1)).isoformat()
    with sqlite3.connect(decision_db) as connection:
        connection.execute("UPDATE health_metrics SET sleep_duration=7.5 WHERE date=?", (DAY.isoformat(),))
    refreshed = get_or_create_daily_decision(DAY, settings=settings)
    assert not refreshed.provisional
    assert refreshed.based_on == DAY.isoformat()


def test_remote_provider_without_config_approval_sends_nothing(decision_db):
    class ForbiddenModel:
        def generate_json(self, *args, **kwargs):
            raise AssertionError("Remote model must not be called")

    settings = replace(get_settings(), db_path=decision_db, llm_provider="openai",
                       allow_remote_llm=False, remote_athlete_data_approved=False)
    result = get_or_create_daily_decision(DAY, settings=settings, llm=ForbiddenModel())
    assert result.headline.endswith("today.")
