"""V2 Coach and Me views use invented values and no provider calls."""

import re
import sqlite3
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from config import get_settings
from db.migration_runner import upgrade_database
from web.app import create_app
from web.view_models.coach import (
    coach_availability,
    coach_evidence_chip,
    coach_turns,
    context_chip,
    context_question,
    proposed_change_question,
)
from web.view_models.me import me_view


def test_coach_availability_and_usage():
    assert coach_availability("ollama", 7, 40, False)["usage"] == "7 of 40 questions today"
    assert not coach_availability("ollama", 7, 40, False)["disabled"]
    assert coach_availability("ollama", 40, 40, False)["disabled"]
    assert "tomorrow" in coach_availability("ollama", 40, 40, False)["reason"]
    assert coach_availability("openai", 0, 40, False)["disabled"]
    assert not coach_availability("openai", 0, 40, True)["disabled"]
    assert coach_availability("none", 0, 40, False)["disabled"]


def test_stored_evidence_uses_today_display_wording():
    assert coach_evidence_chip({"id": "READINESS", "metric": "Readiness",
                                "display": "84/100", "source": "metrics.readiness"}) == {
        "label": "Recovery", "value": "84", "source": "metrics.readiness"}
    assert coach_evidence_chip({"metric": "Load ratio", "display": "0.72",
                                "source": "metrics.load_ratio"}) == {
        "label": "Load", "value": "72% of usual", "source": "metrics.load_ratio"}
    assert coach_evidence_chip({"metric": "HRV", "display": "61 ms",
                                "source": "health_metrics.hrv"})["label"] == "HRV"
    assert coach_evidence_chip({"id": "LOAD_RATIO_STATUS", "metric": "Load ratio status",
                                "display": "below safe range 0.8–1.3", "source": "metrics.load"}) == {
        "label": "Load status", "value": "below safe range 80–130% of usual", "source": "metrics.load"}


def test_context_chips_and_stored_turns_are_presented_without_mutation():
    activity = {"id": 42, "date": "Thu 22 Oct", "sport": "running", "label": "Easy run"}
    assert context_chip("training")["label"] == "About: this week"
    assert context_chip("today", activity) == {"label": "About: this run · Thu 22 Oct",
                                              "href": "/activities/42"}
    assert context_question("How hard?", "today") == "About today: How hard?"
    stored = [{"question": "About today: Why easy?", "answer": "Make tomorrow's run easy.",
               "evidence": [{"metric": "HRV", "display": "61 ms", "source": "health_metrics.hrv"}],
               "cards": [activity], "activity_ids": [42]}]
    shown = coach_turns(stored)
    assert shown[0]["display_question"] == "Why easy?"
    assert shown[0]["evidence_chips"][0]["label"] == "HRV"
    assert shown[0]["suggest_change"]
    assert "Change my plan" in proposed_change_question(shown[0]["answer"])
    assert stored[0]["question"] == "About today: Why easy?"
    with pytest.raises(ValueError):
        proposed_change_question("Your recovery is steady.")


def test_me_view_never_includes_credentials():
    context = {"provider": "openai", "messages": {"morning_enabled": True}}
    view = me_view(context, telegram_configured=True, garmin_configured=False,
                   public_link_configured=False, version="0.1.0", source_url="https://example.org/source")
    assert view["telegram_status"] == "Set"
    assert view["garmin_status"] == "Not set"
    assert view["provider_location"] == "Remote"
    assert all(item[1] == "Set in .env" for item in view["env_settings"])
    assert not any(re.search(r"token|password|secret", str(value), re.I)
                   for key, value in view.items() if key not in {"env_settings", "notifications"})


@pytest.fixture
def web_settings(tmp_path):
    settings = replace(get_settings(), db_path=tmp_path / "v2-coach.db", llm_provider="ollama",
                       telegram_bot_token="private-fixture-token", telegram_chat_id="private-fixture-id",
                       garmin_email="private-fixture@example.org", garmin_password="private-fixture-password")
    upgrade_database(settings.db_path)
    with sqlite3.connect(settings.db_path) as connection:
        connection.execute("INSERT INTO users(id,age,max_hr,marathon_goal_time,running_goal_time) "
                           "VALUES(?,?,?,?,?)", (settings.default_user_id, 30, 190,
                           "04:00:00", "04:00:00"))
    return settings


def test_coach_page_context_and_me_never_render_secrets(web_settings):
    with TestClient(create_app(web_settings, password="")) as client:
        coach = client.get("/coach?context=training")
        assert coach.status_code == 200
        assert "About: this week" in coach.text and "History" in coach.text
        assert "v2-coach-panel" not in coach.text or "v2-coach-page" in coach.text
        me = client.get("/settings")
        assert me.status_code == 200 and "Set in .env" in me.text
        assert "AGPL-3.0" in me.text and "Source code" in me.text
        for secret in (web_settings.telegram_bot_token, web_settings.telegram_chat_id,
                       web_settings.garmin_email, web_settings.garmin_password):
            assert secret not in me.text


def test_disabled_coach_post_does_not_call_provider(web_settings, monkeypatch):
    settings = replace(web_settings, llm_provider="openai", allow_remote_llm=False,
                       remote_athlete_data_approved=False)
    monkeypatch.setattr("web.routes.pages.ask_coach", lambda *args, **kwargs:
                        pytest.fail("provider should not be called"))
    with TestClient(create_app(settings, password="")) as client:
        page = client.get("/coach")
        assert "disabled" in page.text and "Remote coaching is off" in page.text
        assert re.search(r'id="coach-question"[^>]*disabled', page.text)
        assert re.search(r'class="v2-chat-send"[^>]*disabled', page.text)
        assert page.text.index("Remote coaching is off") < page.text.index('class="v2-chat-composer"')
        response = client.post("/coach/ask", data={"question": "How am I?"},
                               headers={"HX-Request": "true"})
        assert response.status_code == 200 and "Remote coaching is off" in response.text


def test_daily_limit_disables_coach_input(web_settings):
    day = datetime.now(ZoneInfo(web_settings.local_timezone)).date().isoformat()
    settings = replace(web_settings, coach_daily_call_limit=1)
    with sqlite3.connect(settings.db_path) as connection:
        connection.execute("INSERT INTO coach_llm_calls(user_id,local_day,created_at) "
                           "VALUES(?,?,?)", (settings.default_user_id, day, day))
    with TestClient(create_app(settings, password="")) as client:
        page = client.get("/coach")
        assert "question limit has been reached" in page.text and 'id="coach-question"' in page.text
        assert re.search(r'id="coach-question"[^>]*disabled', page.text)
        assert re.search(r'class="v2-chat-send"[^>]*disabled', page.text)
        assert page.text.index("question limit has been reached") < page.text.index('class="v2-chat-composer"')


def test_coach_composer_and_scroll_hooks_are_present():
    root = Path(__file__).resolve().parents[1]
    css = (root / "web/static/css/v2.css").read_text()
    js = (root / "web/static/js/v2.js").read_text()
    assert ".v2-chat-thread{" in css and "padding:28px 0 56px" in css
    assert ".v2-chat-bottom{" in css and "background:var(--surface)" in css
    assert ".v2-chat-send:disabled{background:var(--surface-raised)" in css
    assert "DOMContentLoaded" in js and "htmx:afterSwap" in js
    assert "thread.scrollTop = thread.scrollHeight" in js


def test_stored_answer_shows_evidence_and_suggest_creates_proposal_request(web_settings, monkeypatch):
    import json

    with sqlite3.connect(web_settings.db_path) as connection:
        connection.execute("INSERT INTO coach_chat_turns(user_id,question,answer,evidence_json,activity_ids_json,"
                           "tool_calls_json,model_provider,model_name,prompt_version,created_at) "
                           "VALUES(?,?,?,?,?,?,?,?,?,?)", (web_settings.default_user_id,
                           "About today: Why easy?", "Make tomorrow's run easy.",
                           json.dumps([{"metric": "HRV", "display": "61 ms", "source": "fixture.hrv"}]),
                           "[]", "[]", "ollama", "fixture", "chat-v1", "2026-10-22 10:00"))
    calls = []
    monkeypatch.setattr("web.routes.pages.ask_coach", lambda *args, **kwargs: calls.append(args[2]))
    with TestClient(create_app(web_settings, password="")) as client:
        page = client.get("/coach")
        assert "HRV 61 ms" in page.text and "Suggest this change" in page.text
        result = client.post("/coach/suggest", data={"answer": "Make tomorrow's run easy."},
                             follow_redirects=False)
        assert result.status_code == 303 and result.headers["location"] == "/plan"
        assert calls == ["Change my plan: Make tomorrow's run easy."]
