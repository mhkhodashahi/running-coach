"""Worker scheduling uses synthetic databases and a fake transport."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from coach import planning
from coach.proposals import SUPPRESS_PROPOSAL_NOTICE
from config import get_settings
from db.migration_runner import upgrade_database
from services.telegram_chatbot import TelegramTrainingChatBot
from services.telegram_service import TelegramService
from worker import jobs
from worker.__main__ import acquire_lock
from worker.messages import OutboundMessage
from worker.state import history, in_quiet_hours, preferences, save_preferences


class FakeTelegram:
    configured = True

    def __init__(self):
        self.messages = []
        self.keyboards = []

    def send_message(self, html, keyboard=(), plain=None):
        del plain
        self.messages.append(html)
        self.keyboards.append(keyboard)

    def send_text(self, text, recipient=None):
        del recipient
        self.messages.append(text)

    def redact(self, text):
        return text.replace("secret", "[redacted]")

    def send_rating_prompt(self, text, activity_id):
        self.messages.append(f"rating {activity_id}: {text}")

    def acknowledge_callback(self, callback_id, text):
        self.messages.append(text)


@pytest.fixture
def worker_db(tmp_path):
    database = tmp_path / "worker.db"
    upgrade_database(database)
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO users(id,name,age,gender,weight,height,max_hr,marathon_goal_time) "
                   "VALUES(1,'Invented',30,'other',70,170,190,'04:00:00')")
    return database


def _settings(database):
    return replace(get_settings(), db_path=database, default_user_id=1,
                   telegram_bot_token="secret", telegram_chat_id="1", llm_provider="none")


def _clock(hour, minute=0):
    return datetime(2026, 10, 26, hour, minute, tzinfo=ZoneInfo("Europe/Berlin"))


def test_morning_waits_and_sends_once_after_sleep_and_hrv(worker_db, monkeypatch):
    settings = _settings(worker_db)
    telegram = FakeTelegram()
    monkeypatch.setattr(jobs, "morning_payload", lambda *_args, **_kwargs: "Morning decision")
    monkeypatch.setattr(jobs, "dispatch_effort_prompts", lambda *_args: 0)
    jobs.tick(settings, _clock(7), telegram, sync_job=lambda: None)
    assert telegram.messages == []
    with sqlite3.connect(worker_db) as db:
        db.execute("INSERT INTO health_metrics(user_id,date,sleep_duration,hrv) VALUES(1,'2026-10-26',8,60)")
    jobs.tick(settings, _clock(7, 20), telegram, sync_job=lambda: None)
    jobs.tick(settings, _clock(7, 21), telegram, sync_job=lambda: None)
    assert telegram.messages == ["Morning decision"]
    assert history(worker_db, 1)[0]["status"] == "sent"


def test_latest_morning_fallback_and_restart(worker_db, monkeypatch):
    telegram = FakeTelegram()
    monkeypatch.setattr(jobs, "morning_payload", lambda *_args, **_kwargs: "Provisional, based on yesterday")
    monkeypatch.setattr(jobs, "dispatch_effort_prompts", lambda *_args: 0)
    jobs.tick(_settings(worker_db), _clock(10), telegram, sync_job=lambda: None)
    jobs.tick(_settings(worker_db), _clock(10, 1), telegram, sync_job=lambda: None)
    assert telegram.messages == ["Provisional, based on yesterday"]


@pytest.mark.parametrize("new_intensity,expected_updates", [("hard", 1), ("easy", 0)])
def test_late_health_data_sends_only_changed_intensity_once(worker_db, monkeypatch,
                                                             new_intensity, expected_updates):
    from types import SimpleNamespace

    settings = _settings(worker_db)
    telegram = FakeTelegram()
    monkeypatch.setattr(jobs, "dispatch_effort_prompts", lambda *_args: 0)
    monkeypatch.setattr(jobs, "morning_payload", lambda *_args, **_kwargs: OutboundMessage(
        "<b>Easy day — waiting for your data</b>", "Easy day — waiting for your data"))
    jobs.tick(settings, _clock(10), telegram, sync_job=lambda: None)
    assert len(telegram.messages) == 1
    with sqlite3.connect(worker_db) as db:
        db.execute("INSERT INTO health_metrics(user_id,date,sleep_duration,hrv) VALUES(1,'2026-10-26',8,60)")
    monkeypatch.setattr(jobs, "_decision", lambda *_args: SimpleNamespace(
        intensity=new_intensity, headline=f"{new_intensity.title()} today.", rule="hard_allowed",
        facts=({"id": "LOAD_RATIO", "display": "0.99"},)))
    jobs.tick(settings, _clock(11, 30), telegram, sync_job=lambda: None)
    jobs.tick(settings, _clock(11, 31), telegram, sync_job=lambda: None)
    assert len(telegram.messages) == 1 + expected_updates
    if expected_updates:
        assert telegram.messages[-1] == f"<b>Data is in. {new_intensity.title()} today: load 0.99, normal.</b>"
    assert len([row for row in history(worker_db, 1) if row["job"] == "morning_update"]) == 1


def test_quiet_hours_pause_and_lock(worker_db, monkeypatch):
    telegram = FakeTelegram()
    monkeypatch.setattr(jobs, "health_ready", lambda *_args: True)
    monkeypatch.setattr(jobs, "morning_payload", lambda *_args, **_kwargs: "Morning")
    monkeypatch.setattr(jobs, "dispatch_effort_prompts", lambda *_args: 0)
    save_preferences(worker_db, 1, {"quiet_start": "06:00", "quiet_end": "08:00"})
    jobs.tick(_settings(worker_db), _clock(7), telegram, sync_job=lambda: None)
    assert not telegram.messages
    jobs.tick(_settings(worker_db), _clock(8), telegram, sync_job=lambda: None)
    assert telegram.messages == ["Morning"]
    save_preferences(worker_db, 1, {"paused": 1})
    jobs.tick(_settings(worker_db), _clock(17), telegram, sync_job=lambda: None)
    assert len(telegram.messages) == 1
    assert preferences(worker_db, 1)["paused"] == 1
    lock = acquire_lock(worker_db.with_suffix(".worker.lock"))
    try:
        with pytest.raises(RuntimeError, match="already running"):
            acquire_lock(worker_db.with_suffix(".worker.lock"))
    finally:
        lock.close()


def test_equal_quiet_hours_mean_no_quiet_period():
    assert not in_quiet_hours(_clock(7), "07:00", "07:00")


def test_uncertain_delivery_is_never_repeated(worker_db):
    telegram = FakeTelegram()
    telegram.send_text = lambda _text: (_ for _ in ()).throw(RuntimeError("secret timeout"))
    first = jobs.deliver(_settings(worker_db), telegram, "morning", _clock(7).date(), _clock(7), lambda: "hello")
    second = jobs.deliver(_settings(worker_db), telegram, "morning", _clock(7).date(), _clock(7), lambda: "hello")
    assert not first.sent and not second.sent
    assert "secret" not in history(worker_db, 1)[0]["error"]


def test_telegram_redacts_token_in_transport_error(monkeypatch):
    service = TelegramService(_settings(__import__("pathlib").Path("/tmp/unused.db")))
    monkeypatch.setattr("requests.post", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("https://api.telegram.org/botsecret/sendMessage")))
    with pytest.raises(RuntimeError) as error:
        service.send_text("test")
    assert "secret" not in str(error.value)


def test_html_transport_sets_parse_mode_and_inline_keyboard(monkeypatch):
    sent = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    monkeypatch.setattr("requests.post", lambda _url, **kwargs: (sent.append(kwargs["json"]), Response())[1])
    TelegramService(_settings(__import__("pathlib").Path("/tmp/unused.db"))).send_message(
        "<b>Easy day</b>", (({"text": "0", "callback_data": "rpe:1:0"},),))
    assert sent[0]["parse_mode"] == "HTML"
    assert sent[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "rpe:1:0"


def test_html_rejection_uses_plain_text_fallback_with_keyboard(monkeypatch):
    sent = []

    class Response:
        def __init__(self, status):
            self.status_code = status

        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": self.status_code == 200,
                    "description": "Bad Request: can't parse entities"}

    def post(_url, **kwargs):
        sent.append(kwargs["json"])
        return Response(400 if len(sent) == 1 else 200)

    monkeypatch.setattr("requests.post", post)
    result = TelegramService(_settings(__import__("pathlib").Path("/tmp/unused.db"))).send_message(
        "<b>Morning</b>", (({"text": "0", "callback_data": "rpe:1:0"},),), "Morning")
    assert result == "plain"
    assert len(sent) == 2
    assert sent[1]["text"] == "Morning" and "parse_mode" not in sent[1]
    assert sent[1]["reply_markup"] == sent[0]["reply_markup"]


def test_proposal_keyboard_has_link_only_with_public_url(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    def post(_url, **kwargs):
        captured.update(kwargs["json"])
        return Response()

    monkeypatch.setattr("requests.post", post)
    settings = _settings(__import__("pathlib").Path("/tmp/unused.db"))
    TelegramService(settings).send_proposal_prompt("Review", 7)
    buttons = captured["reply_markup"]["inline_keyboard"]
    assert {button["callback_data"] for row in buttons for button in row} == {
        "proposal:7:apply", "proposal:7:dismiss"}
    TelegramService(replace(settings, public_url="https://example.org")).send_proposal_prompt("Review", 7)
    assert captured["reply_markup"]["inline_keyboard"][-1][0]["url"] == "https://example.org/plan"
    assert captured["parse_mode"] == "HTML"


def test_garmin_retry_has_bounded_backoff():
    attempts = []
    waits = []

    def flaky():
        attempts.append(True)
        if len(attempts) < 3:
            raise RuntimeError("temporary Garmin failure")

    jobs.retry_sync(flaky, waits.append)
    assert len(attempts) == 3
    assert waits == [1, 2]


def test_telegram_retries_explicit_rejection_only(monkeypatch):
    calls = []
    waits = []

    class Response:
        headers = {"Retry-After": "1"}

        def __init__(self, status):
            self.status_code = status

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("rejected")

        def json(self):
            return {"ok": True}

    def post(*_args, **_kwargs):
        calls.append(True)
        return Response(429 if len(calls) == 1 else 200)

    monkeypatch.setattr("requests.post", post)
    monkeypatch.setattr("services.telegram_service.time.sleep", waits.append)
    TelegramService(_settings(__import__("pathlib").Path("/tmp/unused.db"))).send_text("test")
    assert len(calls) == 2 and waits == [1]


def test_day_review_dispatches_rating_keyboard_once(worker_db, monkeypatch):
    telegram = FakeTelegram()
    monkeypatch.setattr(jobs, "day_review_payload", lambda *_args, **_kwargs: "Day review")
    calls = []

    def prompt(_settings, _user_id, service):
        calls.append(True)
        if len(calls) == 1:
            service.send_rating_prompt("How hard?", 42)
        return 1

    monkeypatch.setattr(jobs, "dispatch_effort_prompts", prompt)
    jobs.tick(_settings(worker_db), _clock(17), telegram, sync_job=lambda: None)
    assert telegram.messages[-2:] == ["Day review", "rating 42: How hard?"]


def test_day_review_uses_stored_minutes_for_extra_session(worker_db):
    with sqlite3.connect(worker_db) as db:
        db.execute("INSERT INTO activities(user_id,date,type,distance,duration,avg_hr) "
                   "VALUES(1,'2026-10-26','running',5,30,140)")
    payload = jobs.day_review_payload(_settings(worker_db), _clock(17).date())
    assert "Running 30 min (extra)" in payload.plain
    assert "Running 0 min" not in payload.plain


def test_worker_rating_prompt_uses_shared_recent_selector(worker_db):
    with sqlite3.connect(worker_db) as db:
        db.execute("INSERT INTO activities(user_id,date,type,distance,duration) "
                   "VALUES(1,'2026-10-20','running',5,30)")
        db.execute("INSERT INTO activities(user_id,date,type,distance,duration) "
                   "VALUES(1,'2026-10-26','running',5,30)")
    found = jobs._unrated(_settings(worker_db), _clock(17))
    assert len(found) == 1 and "Mon 26 Oct" in found[0][1]


def test_weekly_review_proposes_without_applying(worker_db, monkeypatch):
    settings = _settings(worker_db)
    seen = []
    monkeypatch.setattr(jobs, "list_proposals", lambda *_args: [])
    monkeypatch.setattr(jobs, "propose_week", lambda *_args, **kwargs: (
        seen.append(kwargs), {"summary": "Invented plan"})[1])
    monkeypatch.setattr(jobs, "get_week", lambda *_args: {"sessions": []})
    monkeypatch.setattr(jobs, "load_model", lambda *_args: __import__("types").SimpleNamespace(cap=None))
    text = jobs.weekly_message(settings, _clock(18).date(), use_llm=False)
    assert seen[0]["code_only"] is True
    assert "Invented plan" in text


def test_proposal_button_refuses_stale_and_keeps_allowlist(worker_db, monkeypatch):
    telegram = FakeTelegram()
    settings = _settings(worker_db)
    bot = TelegramTrainingChatBot(settings=settings, telegram_service=telegram, chat_service=object())
    monkeypatch.setattr("services.telegram_chatbot.get_proposal", lambda *_args: {
        "changes": [{"id": 1}], "status": "pending"})
    monkeypatch.setattr("services.telegram_chatbot.apply", lambda *_args: (_ for _ in ()).throw(
        ValueError("Proposal is stale because the plan changed")))
    unauthorized = {"callback_query": {"id": "x", "data": "proposal:1:apply",
                                      "message": {"chat": {"id": 2}}}}
    authorized = {"callback_query": {"id": "x", "data": "proposal:1:apply",
                                    "message": {"chat": {"id": 1}}}}
    assert not bot.handle_update(unauthorized).authorized
    expected = ("This proposal is out of date because your plan changed. "
                "Send /plan or open the app for a fresh one.")
    assert bot.handle_update(authorized).reply == expected
    assert telegram.messages == [expected]


def test_pause_command_prevents_scheduled_message(worker_db):
    telegram = FakeTelegram()
    bot = TelegramTrainingChatBot(settings=_settings(worker_db), telegram_service=telegram, chat_service=object())
    result = bot.handle_update({"message": {"chat": {"id": 1}, "text": "/pause"}})
    assert "paused" in result.reply
    assert preferences(worker_db, 1)["paused"] == 1


def test_auto_opinion_is_metered_and_attempted_once(worker_db, monkeypatch):
    with sqlite3.connect(worker_db) as db:
        db.execute("INSERT INTO activities(user_id,date,type,distance,duration) "
                   "VALUES(1,'2026-10-26','running',5000,1800)")
    calls = []

    class Client:
        def generate_json(self, *_args, **_kwargs):
            calls.append("request")
            return {}

    class Agent:
        def __init__(self, *_args):
            pass

        def _count_request(self):
            calls.append("meter")

    class Service:
        def __init__(self, _settings, llm_client):
            self.client = llm_client

        def generate_for_activity(self, **_kwargs):
            self.client.generate_json("system", "data")

    monkeypatch.setattr("llm.factory.get_llm_client", lambda *_args: Client())
    monkeypatch.setattr("coach.agent.CoachAgent", Agent)
    monkeypatch.setattr("services.activity_coaching_service.ActivityCoachingService", Service)
    settings = replace(_settings(worker_db), auto_opinions=True)
    assert jobs.generate_pending_opinions(settings, _clock(10).date(), _clock(10)) == 1
    assert jobs.generate_pending_opinions(settings, _clock(10).date(), _clock(10)) == 0
    assert calls == ["meter", "request"]
    remote = replace(settings, llm_provider="openai", allow_remote_llm=False)
    assert jobs.generate_pending_opinions(remote, _clock(10).date(), _clock(10)) == 0


def test_code_only_weekly_plan_never_constructs_remote_client(worker_db, monkeypatch):
    settings = replace(_settings(worker_db), llm_provider="openai", allow_remote_llm=False)
    monkeypatch.setattr(planning, "_read_version", lambda *_args: None)
    monkeypatch.setattr(planning, "materialize_week", lambda *_args: None)
    monkeypatch.setattr(planning, "_context", lambda *_args: (
        {"sessions": [], "version": 0}, [], planning.LoadModel(None, {}, {}), {}, False,
        planning.HabitPattern({}, {}), None, None, None, None))
    monkeypatch.setattr(planning, "build_habit_week", lambda *_args: planning.WeekBuild(
        (), "Nothing to change", (), (), "already_planned"))
    monkeypatch.setattr(planning, "get_llm_client", lambda *_args: (_ for _ in ()).throw(
        AssertionError("LLM client must not be created")))
    result = planning.propose_week(_clock(10).date(), settings=settings, today=_clock(10).date(), code_only=True)
    assert result["status"] == "already_planned"


def test_scheduled_daily_decision_suppresses_immediate_proposal_notice(worker_db, monkeypatch):
    from types import SimpleNamespace

    def decision(*_args, **_kwargs):
        assert SUPPRESS_PROPOSAL_NOTICE.get() is True
        return SimpleNamespace(headline="Easy today.", explanation="Take it easy.", readiness=60,
                               provisional=False, sports=(), intensity="easy", rule="otherwise_easy",
                               based_on="2026-10-26")

    monkeypatch.setattr(jobs, "get_or_create_daily_decision", decision)
    monkeypatch.setattr(jobs, "_planned", lambda *_args: [])
    text = jobs.morning_message(_settings(worker_db), _clock(10).date(), use_llm=False)
    assert "Easy day" in text
    assert SUPPRESS_PROPOSAL_NOTICE.get() is False
