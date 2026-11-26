"""Release regressions use only invented data, fake providers and temporary files."""

import ast
import sqlite3
import zipfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import llm.openai_client as provider
from config import get_settings
from db.migration_runner import upgrade_database
from db.session import session_scope
from llm.factory import get_llm_client
from llm.schemas import CoachOpinionV2
from scripts.check_distribution import REQUIRED, check_wheel
from services.activity_coaching_service import ActivityCoachingService, _update_activity_memory
from services.coaching_workflow import CoachingWorkflowService
from worker.messages import OutboundMessage


@pytest.fixture
def release_settings(tmp_path):
    settings = replace(get_settings(), base_dir=tmp_path, db_path=tmp_path / "app.db",
                       llm_provider="none", telegram_bot_token="", telegram_chat_id="",
                       allow_remote_llm=False, remote_athlete_data_approved=False)
    upgrade_database(settings.db_path)
    with sqlite3.connect(settings.db_path) as connection:
        connection.execute("INSERT INTO users(id,name,age,gender,weight,height,max_hr,marathon_goal_time) "
                           "VALUES(1,'Fixture',30,'unspecified',70,175,190,'04:00:00')")
        connection.execute("INSERT INTO activities(id,user_id,date,type,distance,duration) "
                           "VALUES(77,1,'2026-01-02','running',5,30)")
    return settings


def test_provider_uses_injected_database_and_approval_not_global(release_settings, monkeypatch, tmp_path):
    other = tmp_path / "other.db"
    upgrade_database(other)
    approved = replace(release_settings, allow_remote_llm=True, remote_athlete_data_approved=True)
    response = SimpleNamespace(output=[], output_text='{"answer":"Measured."}',
                               usage=SimpleNamespace(input_tokens=12, output_tokens=4, total_tokens=16))
    monkeypatch.setattr("openai.OpenAI", lambda **kwargs: SimpleNamespace(
        responses=SimpleNamespace(create=lambda **kwargs: response)))
    monkeypatch.setattr(provider, "get_settings", lambda: pytest.fail("Provider read global settings"))
    client = get_llm_client("openai", "fixture", "fixture", "", "", settings=approved)
    client.coach_step("system", [], [])
    with sqlite3.connect(approved.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM openai_api_calls").fetchone()[0] == 1
    with sqlite3.connect(other) as connection:
        assert connection.execute("SELECT COUNT(*) FROM openai_api_calls").fetchone()[0] == 0
    denied = get_llm_client("openai", "fixture", "fixture", "", "", settings=release_settings)
    with pytest.raises(PermissionError):
        denied.coach_step("system", [], [])


def test_opinion_uses_configured_sessions_and_memory(release_settings, monkeypatch):
    import services.activity_coaching_service as module

    urls = []

    def scoped(url):
        urls.append(url)
        assert url == release_settings.db_url
        return session_scope(url)

    opinion = CoachOpinionV2(headline="Controlled run", assessment="You kept this controlled.",
                             confidence="medium", intent={"planned": None, "detected": "easy"})
    service = ActivityCoachingService(release_settings, llm_client=object())
    monkeypatch.setattr(module, "session_scope", scoped)
    monkeypatch.setattr(service, "_prepare", lambda *args: ({}, "2026-01-02", "Fixture run"))
    monkeypatch.setattr(service, "_request_opinion", lambda *args: (opinion, None))
    monkeypatch.setattr(module, "coach_memory_context", lambda *args, **kwargs: "")
    service.generate_for_activity(user_id=1, activity_id=77)
    assert urls == [release_settings.db_url, release_settings.db_url]
    with sqlite3.connect(release_settings.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM activity_coaching_insights").fetchone()[0] == 1
    assert module.memory_path(release_settings.db_path, 1).exists()


def test_memory_update_uses_supplied_install_directory(tmp_path):
    opinion = CoachOpinionV2(headline="Controlled", assessment="You stayed controlled.", confidence="medium",
                             intent={"planned": None, "detected": "easy"})
    from services.running_coach_memory import load_running_memory, memory_path

    db = tmp_path / "first.db"
    path = memory_path(db, 1)
    _update_activity_memory("2026-01-02", "Fixture", opinion, path=path)
    assert "Fixture" in load_running_memory(path)
    assert "Fixture" not in load_running_memory(memory_path(db, 2))
    assert "Fixture" not in load_running_memory(memory_path(tmp_path / "second.db", 1))


@pytest.mark.parametrize("kind,name", [("daily", "morning_payload"), ("weekly", "weekly_payload")])
def test_digest_delegates_to_current_guarded_workflow(release_settings, monkeypatch, kind, name):
    seen = []

    def render(settings, day, *, use_llm):
        seen.append((settings.db_path, use_llm))
        return OutboundMessage("<b>Measured</b>", "Measured\nUse the code decision.")

    monkeypatch.setattr(f"services.coaching_workflow.{name}", render)
    result = CoachingWorkflowService(release_settings).generate(None, SimpleNamespace(id=1), decision_type=kind)
    assert seen == [(release_settings.db_path, True)]
    assert result["summary"] == "Measured"
    assert result["message_status"] == "not_sent"


def test_digest_does_not_bypass_limit_errors(release_settings, monkeypatch):
    def limited(*args, **kwargs):
        raise RuntimeError("Daily coach LLM call limit reached")

    monkeypatch.setattr("services.coaching_workflow.morning_payload", limited)
    with pytest.raises(RuntimeError, match="limit reached"):
        CoachingWorkflowService(release_settings).generate(None, SimpleNamespace(id=1))


def test_shared_load_and_safety_have_no_planner_dependency():
    for path in ("coach/load_model.py", "coach/week_rules.py", "coach/proposals.py",
                 "services/daily_decision_service.py", "services/daily_plan_service.py"):
        tree = ast.parse(Path(path).read_text())
        assert not any(isinstance(node, ast.ImportFrom) and node.module == "coach.planning"
                       for node in ast.walk(tree)), path
    for path in ("web/settings_page.py", "web/activities.py"):
        source = Path(path).read_text()
        assert "session.get(" not in source
        assert "session.flush(" not in source


def test_web_bind_reads_configuration_first_and_defaults_to_documented_port(monkeypatch):
    import web.__main__ as entry

    monkeypatch.delenv("WEB_HOST", raising=False)
    monkeypatch.delenv("WEB_PORT", raising=False)
    seen = []
    monkeypatch.setattr(entry, "get_settings", lambda: seen.append("settings"))
    monkeypatch.setattr(entry.uvicorn, "run", lambda *args, **kwargs: seen.append(kwargs))
    entry.main()
    assert seen == ["settings", {"host": "127.0.0.1", "port": 8000}]


def test_distribution_rejects_missing_files_and_private_artifacts(tmp_path):
    path = tmp_path / "fixture.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("web/app.py", "")
    with pytest.raises(ValueError, match="missing="):
        check_wheel(path)
    with zipfile.ZipFile(path, "w") as archive:
        for name in REQUIRED:
            archive.writestr(name, "")
        archive.writestr("db/runtime.worker.lock", "private")
    with pytest.raises(ValueError, match="private=.*runtime.worker.lock"):
        check_wheel(path)


def test_example_has_no_credential_placeholders():
    values = dict(line.split("=", 1) for line in Path(".env.example").read_text().splitlines()
                  if "=" in line and not line.startswith("#"))
    for key in ("OPENAI_API_KEY", "GARMIN_EMAIL", "GARMIN_PASSWORD", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        assert values[key] == ""
