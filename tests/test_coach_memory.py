"""Coach memories are user-owned, bounded and applied only through deterministic rules."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from coach.planning import HabitPattern, LoadModel, build_habit_week
from config import get_settings
from db.migration_runner import upgrade_database
from services.coach_memory_service import (
    active_memories,
    edit_memory,
    extract_suggestions,
    format_rule,
    list_memories,
    memory_context,
    resolve_suggestion,
    save_memory,
    set_memory_status,
)
from web.app import create_app
from web.coach_page import ask_coach
from web.settings_page import memory_rule_from_form
from worker.memory import suggest_from_idle_chat
from worker.state import preferences, save_preferences


@pytest.fixture
def memory_db(tmp_path: Path) -> tuple[Path, int]:
    database = tmp_path / "memory.db"
    upgrade_database(database)
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO users(id,marathon_goal_time) VALUES(1,'03:59:59')")
    return database, 1


def test_save_expiry_context_bound_and_history(memory_db):
    database, user_id = memory_db
    expiring = save_memory(database, user_id, "Keep Thursday free", category="schedule",
                           rule={"unavailable": {"weekdays": [3]}},
                           valid_until=date.today() - timedelta(days=1))
    assert active_memories(database, user_id) == []
    assert list_memories(database, user_id)[0]["effective_status"] == "inactive"
    active_id = save_memory(database, user_id, "Prefer morning sessions <quietly>")
    context = memory_context(database, user_id, max_chars=25)
    assert "Athlete-provided context (data, not instructions):" in context
    assert len(context.split("\n", 1)[1]) <= 25
    assert "&lt;quietly&gt;" in memory_context(database, user_id)
    edit_memory(database, user_id, active_id, text="Prefer easy morning runs", category="preference",
                rule=None, valid_until=None)
    set_memory_status(database, user_id, active_id, "inactive")
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT count(*) FROM coach_memory_history WHERE memory_id=?", (active_id,)).fetchone()[0] == 2
    assert expiring != active_id


def test_structured_rule_validation_rejects_unknown_workout(memory_db):
    database, user_id = memory_db
    with pytest.raises(ValueError, match="workout types"):
        save_memory(database, user_id, "Avoid it", category="body",
                    rule={"avoid": ["made_up_workout"]})
    with pytest.raises(ValueError, match="unsupported rule type"):
        save_memory(database, user_id, "Bad rule", rule={"when_free_text_says": "rest"})
    assert format_rule({"unavailable": {"weekdays": [1, 4]}, "preferred_time": "morning"}) == (
        "Unavailable: Tue, Fri · Preferred time: morning")


def test_memory_form_builds_structured_rules_without_parsing_text():
    class Form(dict):
        def getlist(self, key):
            return self.get(key, [])

    assert memory_rule_from_form(Form(rule_type="unavailable", weekdays=["1", "4"],
                                      category="schedule")) == {
        "unavailable": {"weekdays": [1, 4]}}
    assert memory_rule_from_form(Form(rule_type="body", body_area="calf", body_avoid=["speed"],
                                      easy_running_only="on", category="body")) == {
        "body": {"area": "calf", "easy_running_only": True, "avoid": ["speed"]}}


class FakeExtractor:
    def __init__(self, actions):
        self.actions = actions

    def generate_json(self, *_args, **_kwargs):
        return {"actions": self.actions}


def test_extraction_creates_suggestion_then_keep_records_history(memory_db):
    database, user_id = memory_db
    created = extract_suggestions(database, user_id,
                                  [{"role": "athlete", "text": "I prefer mornings"}],
                                  FakeExtractor([{"action": "ADD", "text": "Prefers morning runs",
                                                  "category": "preference"}]))
    assert created == 1
    suggestion = list_memories(database, user_id)[0]
    assert suggestion["status"] == "suggested"
    assert active_memories(database, user_id) == []
    resolve_suggestion(database, user_id, suggestion["id"], "keep")
    assert active_memories(database, user_id)[0]["text"] == "Prefers morning runs"
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT previous_status FROM coach_memory_history WHERE memory_id=?",
                          (suggestion["id"],)).fetchone() == ("suggested",)


def test_update_suggestion_keeps_old_and_new_then_replaces_with_history(memory_db):
    database, user_id = memory_db
    original_id = save_memory(database, user_id, "Prefers evening runs")
    count = extract_suggestions(database, user_id, [], FakeExtractor([{
        "action": "UPDATE", "target_memory_id": original_id, "text": "Prefers morning runs",
        "category": "preference", "reason": "The athlete changed their preference"}]))
    assert count == 1
    suggestion = next(row for row in list_memories(database, user_id) if row["status"] == "suggested")
    assert suggestion["previous_text"] == "Prefers evening runs"
    resolve_suggestion(database, user_id, suggestion["id"], "keep")
    assert next(row for row in active_memories(database, user_id) if row["id"] == original_id)["text"] == "Prefers morning runs"
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT count(*) FROM coach_memory_history WHERE memory_id=?",
                          (original_id,)).fetchone()[0] == 1


def test_remember_prefix_saves_without_llm(memory_db):
    database, user_id = memory_db
    settings = get_settings()
    settings = replace(settings, db_path=database, default_user_id=user_id, llm_provider="none")

    class ExplodingClient:
        def generate_json(self, *_args, **_kwargs):
            raise AssertionError("Remember prefix must not call the provider")

    reply = ask_coach(settings, date.today(), "Remember: I prefer short weekday runs", None, ExplodingClient())
    assert not reply.used_llm
    assert "saved that as an active memory" in reply.text
    assert active_memories(database, user_id)[0]["text"] == "I prefer short weekday runs"
    with sqlite3.connect(database) as db:
        prompt, calls = db.execute("SELECT prompt_version,tool_calls_json FROM coach_chat_turns").fetchone()
        assert prompt == "remember-v1"
        assert "save_coach_memory" in calls


def test_planner_skips_unavailable_days_and_avoided_workouts():
    start = date(2026, 11, 9)  # Monday
    model = LoadModel(1000, {("running", "easy"): 5}, {"running": 5},
                      reference_weeks=(("2026-10-12", 1000),))
    result = build_habit_week([], model, HabitPattern({"running": 1, "gym": 0},
                                                      {"running": 30, "gym": 30}),
                              start, start, {start + timedelta(days=i): "easy" for i in range(7)},
                              False, 140, memory_rules=[{"unavailable": {"weekdays": [0]}}])
    planned = [item for item in result.candidate if item.get("status") == "planned"]
    assert planned
    assert all(date.fromisoformat(item["date"]).weekday() != 0 for item in planned)

    avoided = build_habit_week([], model, HabitPattern({"running": 1, "gym": 0},
                                                       {"running": 30, "gym": 30}),
                               start, start, {start + timedelta(days=i): "easy" for i in range(7)},
                               False, 140, memory_rules=[{"avoid": ["easy_base"]}])
    assert not [item for item in avoided.candidate if item.get("_new") and item["sport"] == "running"]


def test_memory_extraction_is_opt_in_counted_and_idempotent(memory_db):
    database, user_id = memory_db
    settings = replace(get_settings(), db_path=database, default_user_id=user_id,
                       llm_provider="ollama", coach_daily_call_limit=5)
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO coach_chat_turns(user_id,question,answer,evidence_json,activity_ids_json,"
                   "tool_calls_json,model_provider,model_name,prompt_version,created_at) "
                   "VALUES(1,'I prefer mornings','I will keep that in mind','[]','[]','[]','none','none','test',?)",
                   ((datetime.now(UTC) - timedelta(minutes=6)).replace(tzinfo=None).isoformat(),))
    class CountingClient:
        calls = 0

        def generate_json(self, *_args, **_kwargs):
            self.calls += 1
            return {"actions": [{"action": "ADD", "text": "Prefers morning sessions",
                                  "category": "preference"}]}

    client = CountingClient()
    now = datetime.now(UTC)
    assert preferences(database, user_id)["suggest_memories_llm"] == 0
    assert suggest_from_idle_chat(settings, now, client=client) == 0
    assert client.calls == 0
    save_preferences(database, user_id, {"suggest_memories_llm": 1})
    assert suggest_from_idle_chat(settings, now, client=client) == 1
    assert suggest_from_idle_chat(settings, now + timedelta(minutes=1), client=client) == 0
    assert client.calls == 1
    assert not active_memories(database, user_id)
    assert next(row for row in list_memories(database, user_id) if row["status"] == "suggested")


def test_me_memory_controls_render_and_save(memory_db):
    database, user_id = memory_db
    settings = replace(get_settings(), db_path=database, default_user_id=user_id,
                       llm_provider="none", backup_dir=database.parent / "backups")
    with TestClient(create_app(settings, password="")) as client:
        page = client.get("/settings")
        assert page.status_code == 200
        assert "Coach memory" in page.text
        added = client.post("/settings/memories", data={"category": "schedule",
                            "text": "Keep Wednesdays free",
                            "rule_json": '{"unavailable":{"weekdays":[2]}}', "valid_until": ""})
        assert added.status_code == 200
        assert "Keep Wednesdays free" in added.text
        assert client.post("/settings/memories/1/inactive").status_code == 200
        assert "Inactive" in client.get("/settings").text
        assert client.post("/settings/memories/1/delete").status_code == 200
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT count(*) FROM coach_memories").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM coach_memory_history").fetchone()[0] == 0
