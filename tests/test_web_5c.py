"""5c web journeys use only invented fixture values and mocked providers."""

import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from coach.proposals import create_proposal, get_proposal, get_week, manual_session, request_revision
from config import get_settings
from db.migration_runner import upgrade_database
from services.training_chat_service import TrainingChatReply
from web.app import create_app
from web.charts import trend_bars, trend_line, weekly_sport_bars
from web.coach_page import ask_coach
from web.plan_page import plan_context
from web.trends import TrendReply, _fallback, cached_trend_summary, trends_context, validate_trend_reply


@pytest.fixture
def data(tmp_path):
    settings = replace(get_settings(), db_path=tmp_path / "web5c.db", llm_provider="none")
    upgrade_database(settings.db_path)
    day = datetime.now(ZoneInfo(settings.local_timezone)).date()
    with sqlite3.connect(settings.db_path) as connection:
        connection.execute("INSERT INTO users(id,max_hr,age,marathon_goal_time,running_goal_time) "
                           "VALUES(?,?,?,?,?)", (settings.default_user_id, 190, 30, "04:00:00", "04:00:00"))
    return settings, day


def fill_data(settings, day, *, partial=False):
    with sqlite3.connect(settings.db_path) as connection:
        for offset in range(1 if partial else 35):
            connection.execute("INSERT INTO health_metrics(user_id,date,resting_hr,hrv,sleep_duration) "
                               "VALUES(?,?,?,?,?)", (settings.default_user_id,
                               (day - timedelta(days=offset)).isoformat(), 50 + offset % 3, 55, 7.2))
        connection.execute("INSERT INTO activities(id,user_id,date,type,distance,duration,pace,avg_hr) "
                           "VALUES(201,?,?, 'running',5,30,6,140)",
                           (settings.default_user_id, (day - timedelta(days=2)).isoformat()))


@pytest.mark.parametrize("mode", ("empty", "partial", "full"))
def test_three_pages_render_with_invented_data(data, mode):
    settings, day = data
    if mode != "empty":
        fill_data(settings, day, partial=mode == "partial")
    with TestClient(create_app(settings, password="")) as client:
        for path, expected in (("/trends?range=7", "Resting heart rate"),
                               ("/coach", "Attach a session"), ("/plan", "Protected habits")):
            response = client.get(path)
            assert response.status_code == 200, (path, response.text[:400])
            assert expected in response.text
        assert "No data" in client.get("/trends?range=7").text if mode == "empty" else True
        assert client.get("/trends?range=13").status_code == 400


def proposal(settings, day):
    start = day - timedelta(days=day.weekday()) + timedelta(days=7)
    session = {"id": None, "date": start.isoformat(), "sport": "running", "intent": "easy",
               "duration_min": 30, "hr_cap_bpm": 130, "notes": None, "status": "planned"}
    facts = [{"id": "EASY", "metric": "Habit", "display": "easy training", "source": "fixture"}]
    changes = [{"change_type": "add", "session": session, "reason": "Keep training easy.",
                "fact_ids": ["EASY"], "group_id": "run"}]
    created = create_proposal(settings.db_path, settings.default_user_id,
                              "weekly_plan", "An easy session is proposed.", facts, changes)
    return created, start, changes


def test_apply_dismiss_undo_and_stale_routes(data):
    settings, day = data
    fill_data(settings, day)
    created, start, _ = proposal(settings, day)
    group = created["changes"][0]["group_id"]
    with TestClient(create_app(settings, password="")) as client:
        assert "An easy session is proposed" in client.get("/plan").text
        response = client.post(f"/plan/proposals/{created['id']}/apply", data={"group_ids": group})
        assert response.status_code == 200, response.text
        assert get_proposal(settings.db_path, settings.default_user_id, created["id"])["status"] == "applied"
        assert any(item["sport"] == "running" for item in get_week(settings.db_path,
                   settings.default_user_id, start)["sessions"])
        assert client.post("/plan/undo", data={"confirm": "no"}).status_code == 400
        assert client.post("/plan/undo", data={"confirm": "yes"}).status_code == 200
        assert not any(item["sport"] == "running" for item in get_week(settings.db_path,
                       settings.default_user_id, start)["sessions"])
        old, _, _ = proposal(settings, day)
        manual_session(settings.db_path, settings.default_user_id,
                       {"date": start.isoformat(), "sport": "gym", "intent": "light",
                        "duration_min": 30, "hr_cap_bpm": None, "notes": None})
        assert client.post(f"/plan/proposals/{old['id']}/apply", data={"group_ids": "run"}).status_code == 409
        assert get_proposal(settings.db_path, settings.default_user_id, old["id"])["status"] == "stale"
        fresh, _, _ = proposal(settings, day)
        assert client.post(f"/plan/proposals/{fresh['id']}/dismiss").status_code == 200
        assert get_proposal(settings.db_path, settings.default_user_id, fresh["id"])["status"] == "dismissed"


def test_revision_route_supersedes_without_applying(data, monkeypatch):
    settings, day = data
    created, start, changes = proposal(settings, day)

    def revise(proposal_id, text, *, settings, user_id, llm, today):
        return request_revision(settings.db_path, user_id, proposal_id, text, changes)

    monkeypatch.setattr("web.plan_page.revise_week", revise)
    with TestClient(create_app(settings, password="")) as client:
        assert client.post(f"/plan/proposals/{created['id']}/revise",
                           data={"revision": "Make it easier"}).status_code == 200
    assert get_proposal(settings.db_path, settings.default_user_id, created["id"])["status"] == "superseded"
    assert not get_week(settings.db_path, settings.default_user_id, start)["sessions"]


def test_apply_route_accepts_entire_change_group(data):
    settings, day = data
    fill_data(settings, day)
    start = day - timedelta(days=day.weekday()) + timedelta(days=7)
    facts = [{"id": "HABIT", "metric": "Habit", "display": "easy training", "source": "fixture"}]
    changes = [{"change_type": "add", "session": {
        "id": None, "date": (start + timedelta(days=offset)).isoformat(), "sport": "running",
        "intent": "easy", "duration_min": 30, "hr_cap_bpm": 130, "notes": None, "status": "planned"},
        "reason": "Keep training easy.", "fact_ids": ["HABIT"], "group_id": "paired"}
        for offset in (0, 2)]
    created = create_proposal(settings.db_path, settings.default_user_id, "weekly_plan",
                              "Two linked easy sessions.", facts, changes)
    with TestClient(create_app(settings, password="")) as client:
        response = client.post(f"/plan/proposals/{created['id']}/apply", data={"group_ids": "paired"})
        assert response.status_code == 200, response.text
    week = get_week(settings.db_path, settings.default_user_id, start)
    assert len([item for item in week["sessions"] if item["origin"] == "coach"]) == 2


def test_plan_editor_routes_increment_version(data):
    settings, day = data
    start = day - timedelta(days=day.weekday())
    before = get_week(settings.db_path, settings.default_user_id, start)["version"]
    with TestClient(create_app(settings, password="")) as client:
        commitment = client.post("/plan/edit/commitment", data={"weekday": "1", "start_time": "19:00",
            "sport": "volleyball", "kind": "training", "duration_min": "90", "active": "on"})
        habit = client.post("/plan/edit/habit", data={"sport": "gym", "intent": "light",
            "duration_min": "30", "per_week": "2", "active": "on"})
        manual = client.post("/plan/edit/session", data={"date": day.isoformat(), "sport": "running",
            "intent": "easy", "duration_min": "30", "hr_cap_bpm": "130"})
        assert all(response.status_code == 200 for response in (commitment, habit, manual))
    assert get_week(settings.db_path, settings.default_user_id, start)["version"] >= before + 3


def test_plan_request_creates_proposal_not_session(data, monkeypatch):
    settings, day = data
    calls = []

    def draft(question, start, *, settings, user_id, llm, today):
        calls.append(question)
        return proposal(settings, day)[0]

    monkeypatch.setattr("web.coach_page.propose_requested_change", draft)
    reply = ask_coach(settings, day, "Change my plan so Saturday is rest", None)
    assert calls and "proposal" in reply.text
    with sqlite3.connect(settings.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM plan_sessions").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM coach_chat_turns").fetchone()[0] == 1


def test_coach_chat_attaches_user_session_and_renders_stored_thread(data, monkeypatch):
    settings, day = data
    fill_data(settings, day)
    monkeypatch.setattr("web.routes.pages.ask_coach", lambda *args, **kwargs:
                        TrainingChatReply("I see the attached run.", True, (), (201,), ("How was recovery?",)))
    with TestClient(create_app(settings, password="")) as client:
        page = client.get("/coach")
        assert "value=\"201\"" in page.text
        response = client.post("/coach/ask", data={"question": "How was this run?", "activity_id": 201},
                               headers={"HX-Request": "true"})
        assert response.status_code == 200 and "How was recovery?" in response.text
        assert client.post("/coach/ask", data={"question": "How was this run?", "activity_id": 999}).status_code == 400


def test_trend_validator_and_daily_cache(data):
    settings, day = data
    facts = [{"id": "READINESS", "metric": "Readiness", "display": "70/100", "source": "fixture"},
             {"id": "LOAD_RATIO", "metric": "Load ratio", "display": "1.20", "source": "fixture"}]
    payload = {"headline": "Your recovery is steady.",
               "explanation": "I see readiness 70/100 and load ratio 1.20.",
               "evidence_ids": ["READINESS", "LOAD_RATIO"]}

    class FakeLLM:
        calls = 0

        def generate_json(self, *args, **kwargs):
            self.calls += 1
            return payload

    fake = FakeLLM()
    assert validate_trend_reply(TrendReply.model_validate(payload), facts) == ()
    first = cached_trend_summary(settings, day, 7, facts, fake)
    second = cached_trend_summary(settings, day, 7, facts, fake)
    assert first == second and first["source"] == "llm" and fake.calls == 1
    bad = TrendReply.model_validate({**payload, "explanation": "I see readiness 74/100."})
    assert validate_trend_reply(bad, facts)


def test_trend_chart_keeps_gaps_and_labels_decision_shapes():
    chart = trend_line([("2026-06-01", 60), ("2026-06-02", None), ("2026-06-03", 70)],
                       "Readiness", "muted", markers={"2026-06-03": "hard"})
    assert "M48.0" in chart["svg"] and "M558.0" in chart["svg"]
    assert "2026-06-03: Hard" in chart["svg"]
    assert "1 missing" in chart["summary"]


def test_trend_axes_latest_band_and_stacked_weekly_load():
    days = [("2026-06-01", 1.0), ("2026-06-02", 1.2), ("2026-06-03", 1.1)]
    line = trend_line(days, "Load ratio", "load", safe_band=(0.8, 1.3))["svg"]
    assert "0.8" in line and "1.3" in line and "1.10" in line
    assert "Mon 1 Jun" in line and "Wed 3 Jun" in line
    bars = trend_bars(days, "Sleep", 7.5, "sleep")["svg"]
    assert "0 h" in bars and "Mon 1 Jun" in bars
    stacked = weekly_sport_bars({"2026-06-01": {"running": 50, "gym": 30},
                                 "2026-06-08": {"running": 70}}, ("running", "gym"), 100)["svg"]
    assert "01 Jun" in stacked and "08 Jun" in stacked
    assert "Cap 100 TRIMP" in stacked and 'opacity="0.55"' in stacked
    assert "Run</text>" in stacked and "Gym</text>" in stacked
    assert 'stroke="var(--ground)" stroke-width="1"' in stacked
    assert '>0</text>' in line


def test_trend_summary_uses_direction_from_shared_facts():
    facts = [{"id": "HRV_CHANGE", "metric": "Overnight HRV change", "display": "up 4 ms", "source": "fixture"},
             {"id": "RESTING_HR_CHANGE", "metric": "Resting HR change", "display": "down 2 bpm", "source": "fixture"}]
    result = _fallback(facts)
    assert "Overnight HRV is up 4 ms" in result["explanation"]
    assert "Resting HR is down 2 bpm" in result["explanation"]
    assert "I have" not in result["explanation"]


def test_readiness_same_on_today_trend_summary_and_decision_with_missing_today(data):
    settings, day = data
    fill_data(settings, day)
    context = trends_context(settings, day, 7)
    from services.daily_decision_service import build_daily_decision
    decision = build_daily_decision(day, settings.db_path, settings.default_user_id,
                                    settings.local_timezone, settings.sleep_goal_hours)
    readiness = next(chart for chart in context["charts"] if chart["title"] == "Readiness")
    assert f"Latest {round(decision.readiness)} /100" in readiness["svg"]["summary"]


def test_plan_shows_recorded_past_and_future_budget(data):
    settings, today = data
    viewed = today - timedelta(days=today.weekday()) + timedelta(days=4)
    fill_data(settings, viewed)
    with sqlite3.connect(settings.db_path) as connection:
        connection.execute("INSERT INTO activities(id,user_id,date,type,distance,duration,pace,avg_hr) "
                           "VALUES(202,?,?, 'running',5,30,6,140)",
                           (settings.default_user_id, (viewed - timedelta(days=9)).isoformat()))
    planned = viewed + timedelta(days=1)
    manual_session(settings.db_path, settings.default_user_id,
                   {"date": planned.isoformat(), "sport": "running", "intent": "easy",
                    "duration_min": 30, "hr_cap_bpm": 130, "notes": None})
    context = plan_context(settings, viewed)
    days = context["weeks"][0]["days"]
    recorded = next(item for item in days if item["date"] == (viewed - timedelta(days=2)).isoformat())
    assert recorded["actuals"][0]["id"] == 201
    assert recorded["actuals"][0]["status"] == "done"
    assert next(item for item in days if item["date"] == planned.isoformat())["planned_load"] is not None
    assert "Nothing planned" in [item["empty_label"] for item in days]
    assert context["weeks"][0]["actual_total"] is not None
    assert context["weeks"][0]["planned_total"] is not None
    assert context["weeks"][0]["mobile_rows"][0]["kind"] == "summary"
    with TestClient(create_app(settings, password="")) as client:
        page = client.get("/plan")
        assert page.status_code == 200
