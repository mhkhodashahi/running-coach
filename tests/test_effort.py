"""Invented athlete sessions only."""

from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from coach.decision import PriorSession, is_hard_session
from db.models import Activity, ActivityEffort, Base, User
from metrics.effort import (
    calibrate,
    combined_load,
    scaled_session_load,
    sport_multipliers,
    srpe_load,
)
from metrics.load import calibration_and_scales
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
    assert calibrate(((90, 180),) * 4).factor is None
    assert calibrate(((90, 180),) * 4).method == "insufficient_rated_hr_sessions"
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
    assert snapshot.sessions[0].load.value is not None
    assert snapshot.sessions[0].load.value < 360
    assert "trimp_uncalibrated" in snapshot.sessions[0].load.provenance.method


def test_sport_multiplier_threshold_and_unrated_scale():
    pairs = (("football", 100.0, 200.0), ("football", 80.0, 160.0),
             ("football", 120.0, 240.0))
    assert sport_multipliers(pairs[:2]) == {}
    assert sport_multipliers(pairs) == {"football": 2.0}
    unavailable = calibrate(())
    assert scaled_session_load("football", 100, 8, 60, unavailable, {"football": 2})[0] == 100
    assert combined_load("football", None, 8, 60, unavailable)[0] is None
    calibration = calibrate(((100, 200),) * 5)
    assert scaled_session_load("football", 100, 8, 60, calibration, {})[0] == 100
    assert scaled_session_load("football", 100, None, 60, calibration, {})[0] == 100
    assert scaled_session_load("football", 100, None, 60, calibration, {"football": 2}) == (200, "trimp_scaled_sport_median")
    assert scaled_session_load("football", 100, 8, 60, calibration, {"football": 2})[0] == 240
    assert scaled_session_load("running", 100, 8, 60, calibration, {"football": 2})[0] == 100


def test_last_two_weeks_rated_do_not_inflate_identical_training_load_ratio():
    day = date(2026, 5, 28)
    health = tuple(HealthDay(day - timedelta(days=offset), 60, 50, 7.5) for offset in range(29))
    activities = tuple(MetricActivity(index + 1, day - timedelta(days=week * 7 + offset),
                                      "football", 60, 120,
                                      rpe=8 if week < 2 else None)
                       for week in range(4) for offset in (1, 3, 5)
                       for index in (week * 3 + (offset - 1) // 2,))
    profile = Profile(1, 180, 40)
    unmodified = tuple(MetricActivity(row.id, row.day, row.type, row.duration, row.avg_hr)
                       for row in activities)
    before = build_daily_snapshot(Inputs(profile, health, unmodified), day, "Europe/Berlin", 7.5)
    after = build_daily_snapshot(Inputs(profile, health, activities), day, "Europe/Berlin", 7.5)
    _, multipliers = calibration_and_scales(activities, profile, health, day, "Europe/Berlin")
    assert multipliers["football"] > 1
    assert before.load.ratio.value == pytest.approx(1.0)
    assert abs(after.load.ratio.value - before.load.ratio.value) <= 0.05
    assert all(session.load.value == pytest.approx(after.sessions[0].load.value) for session in after.sessions)


def test_future_rated_sessions_do_not_change_past_sport_scale():
    day = date(2026, 5, 28)
    activities = tuple(MetricActivity(index, day + timedelta(days=index - 3),
                                      "volleyball", 60, 120, rpe=8) for index in range(5))
    health = tuple(HealthDay(day - timedelta(days=offset), 60) for offset in range(7))
    calibration, multipliers = calibration_and_scales(activities, Profile(1, 180, 40),
                                                      health, day, "Europe/Berlin")
    assert calibration.rated_hr_sessions == 4
    assert calibration.factor is None
    assert multipliers == {}
    later_calibration, later_multipliers = calibration_and_scales(
        activities, Profile(1, 180, 40), health, day + timedelta(days=1), "Europe/Berlin")
    assert later_calibration.rated_hr_sessions == 5
    assert later_calibration.factor is not None
    assert "volleyball" in later_multipliers


@pytest.mark.parametrize("rated_count", range(5))
def test_zero_to_four_ratings_match_unrated_loads_exactly(rated_count):
    day = date(2026, 5, 28)
    health = tuple(HealthDay(day - timedelta(days=offset), 60, 50, 7.5) for offset in range(29))
    activities = tuple(MetricActivity(index + 1, day - timedelta(days=index), "gym", 60, 120,
                                      rpe=8 if index < rated_count else None) for index in range(6))
    baseline = tuple(replace(activity, rpe=None) for activity in activities)
    rated = build_daily_snapshot(Inputs(Profile(1, 180, 40), health, activities), day, "Europe/Berlin", 7.5)
    unrated = build_daily_snapshot(Inputs(Profile(1, 180, 40), health, baseline), day, "Europe/Berlin", 7.5)
    assert [session.load.value for session in rated.sessions] == [session.load.value for session in unrated.sessions]
    assert rated.load.ratio.value == unrated.load.ratio.value


def test_fifth_hr_backed_rating_enables_calibrated_load():
    day = date(2026, 5, 28)
    health = tuple(HealthDay(day - timedelta(days=offset), 60, 50, 7.5) for offset in range(29))
    activities = tuple(MetricActivity(index + 1, day - timedelta(days=index), "football", 60, 120,
                                      rpe=8 if index < 5 else None) for index in range(6))
    four = tuple(replace(activity, rpe=None) if activity.id == 5 else activity for activity in activities)
    four_snapshot = build_daily_snapshot(Inputs(Profile(1, 180, 40), health, four), day, "Europe/Berlin", 7.5)
    five_snapshot = build_daily_snapshot(Inputs(Profile(1, 180, 40), health, activities), day, "Europe/Berlin", 7.5)
    assert all("calibrated_srpe" not in session.load.provenance.method for session in four_snapshot.sessions)
    assert any("calibrated_srpe" in session.load.provenance.method for session in five_snapshot.sessions)
    assert five_snapshot.sessions[-1].load.value > four_snapshot.sessions[-1].load.value


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
