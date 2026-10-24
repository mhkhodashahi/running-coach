"""Invented athlete sessions only."""

from contextlib import contextmanager
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from coach.decision import PriorSession, is_hard_session
from db.models import Activity, ActivityEffort, Base, User
from metrics.effort import DEFAULT_TRIMP_PER_SRPE, calibrate, combined_load, srpe_load
from metrics.models import Activity as MetricActivity
from metrics.models import HealthDay, Inputs, Profile
from metrics.snapshot import build_daily_snapshot
from services.coach_facts import build_facts, effort_vs_hr
from services.effort_service import (
    mark_prompt_sent,
    prompt_candidates,
    queue_new_activities,
    rate_activity,
    unrated_activities,
)
from services.telegram_chatbot import TelegramTrainingChatBot


def test_srpe_calibration_and_max_rule():
    assert srpe_load(8, 90) == 720
    with pytest.raises(ValueError):
        srpe_load(11, 20)
    assert calibrate(((90, 180),) * 4).factor == DEFAULT_TRIMP_PER_SRPE
    calibrated = calibrate(((90, 180), (100, 200), (110, 220), (120, 240), (500, 500)))
    assert calibrated.factor == 0.5
    assert calibrated.method == "median_hr_trimp_per_srpe"
    assert combined_load("football", 100, 8, 90, calibrated)[0] == 360
    assert combined_load("gym", 400, 8, 90, calibrated)[0] == 400
    assert combined_load("running", 100, 8, 90, calibrated)[0] == 100
    assert combined_load("football", None, None, 90, calibrated)[0] is None
    assert combined_load("football", None, 8, 90, calibrated)[0] == 360


def test_snapshot_effort_load_and_future_rating_ignored():
    day = date(2026, 5, 20)
    activities = (MetricActivity(1, day, "football", 90, 110, rpe=8),
                  MetricActivity(2, day + timedelta(days=1), "gym", 60, 130, rpe=10))
    health = tuple(HealthDay(day - timedelta(days=i), 60, 50, 7.5) for i in range(29))
    snapshot = build_daily_snapshot(Inputs(Profile(1, 180, 40), health, activities), day, "Europe/Berlin", 7.5)
    assert len(snapshot.sessions) == 1
    assert snapshot.sessions[0].load.value == 360
    assert "calibrated_srpe" in snapshot.sessions[0].load.provenance.method


def test_hard_session_uses_rating_when_present():
    when = datetime(2026, 5, 20)
    assert is_hard_session(PriorSession(when, "football"))
    assert not is_hard_session(PriorSession(when, "football", rpe=6))
    assert is_hard_session(PriorSession(when, "football", rpe=7))
    assert is_hard_session(PriorSession(when, "running", rpe=8))
    assert is_hard_session(PriorSession(when, "football", "tempo", rpe=2))
    assert is_hard_session(PriorSession(when, "football", z4_plus_percent=15, rpe=2))
    assert effort_vs_hr(8, 80) == "higher than HR suggests"
    assert effort_vs_hr(3, 50) == "lower than HR suggests"
    assert effort_vs_hr(5, 80) == "matches"


def test_activity_facts_include_effort_and_code_mismatch():
    facts = build_facts(4, {"selected_activity": {"id": 4, "date": "2026-05-20"},
                            "effort_rpe": 8, "effort_low_zone_share": 80})
    by_id = {item["id"]: item for item in facts}
    assert by_id["EFFORT_RPE"]["display"] == "8/10"
    assert "80.0% in Z1–Z2: higher than HR suggests" in by_id["EFFORT_VS_HR"]["display"]


def test_prompt_once_reminder_once_and_rating_change(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'effort.db'}")
    Base.metadata.create_all(engine)
    now = datetime(2026, 5, 21, 10)
    with Session(engine) as session:
        session.add(User(id=1))
        session.add_all([Activity(id=1, user_id=1, date=now.date(), type="football", distance=1, duration=90),
                         Activity(id=2, user_id=1, date=now.date(), type="walking", distance=1, duration=20)])
        session.flush()
        queue_new_activities(session, {1, 2})
        assert [(a.id, reminder) for a, reminder in prompt_candidates(session, 1, now)] == [(1, False)]
        mark_prompt_sent(session, 1, False, now)
        assert prompt_candidates(session, 1, now + timedelta(hours=11)) == []
        assert [(a.id, reminder) for a, reminder in prompt_candidates(session, 1, now + timedelta(hours=12))] == [(1, True)]
        mark_prompt_sent(session, 1, True, now + timedelta(hours=12))
        assert prompt_candidates(session, 1, now + timedelta(days=2)) == []
        rate_activity(session, 1, 1, 8, "web", now=now)
        rate_activity(session, 1, 1, 6, "telegram", now=now + timedelta(days=1))
        assert session.get(ActivityEffort, 1).rpe == 6
        assert [row.id for row in unrated_activities(session, 1)] == []
        with pytest.raises(ValueError):
            rate_activity(session, 2, 1, 3, "web")
    engine.dispose()


def test_telegram_rating_callback_checks_allowlist(monkeypatch):
    calls = []

    class FakeTelegram:
        def acknowledge_callback(self, callback_id, reply):
            calls.append((callback_id, reply))

    @contextmanager
    def fake_session():
        yield object()

    monkeypatch.setattr("services.telegram_chatbot.session_scope", fake_session)
    monkeypatch.setattr("services.telegram_chatbot.rate_activity",
                        lambda session, activity_id, user_id, rpe, source: calls.append((activity_id, user_id, rpe, source)))
    bot = TelegramTrainingChatBot(settings=SimpleNamespace(telegram_chat_id="111", default_user_id=1),
                                  telegram_service=FakeTelegram(), chat_service=object())
    rejected = bot.handle_update({"callback_query": {"id": "x", "message": {"chat": {"id": 222}},
                                                     "data": "rpe:7:8"}})
    assert not rejected.authorized and calls == []
    accepted = bot.handle_update({"callback_query": {"id": "y", "message": {"chat": {"id": 111}},
                                                     "data": "rpe:7:8"}})
    assert accepted.handled and calls == [(7, 1, 8, "telegram"), ("y", "Effort saved: 8/10.")]
