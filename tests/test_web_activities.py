"""Activity web routes against invented rows; no real athlete data or provider calls."""

import json
import sqlite3
from dataclasses import replace
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from config import get_settings
from db.migration_runner import upgrade_database
from web.app import create_app

DAY = date(2026, 10, 23)


@pytest.fixture
def activity_db(tmp_path):
    database = tmp_path / "activities.db"
    upgrade_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO users(id,max_hr,age,marathon_goal_time,running_goal_time) "
                           "VALUES(1,190,30,'04:00:00','04:00:00')")
        for offset in range(35):
            connection.execute("INSERT INTO health_metrics(user_id,date,resting_hr,hrv,sleep_duration) "
                               "VALUES(1,?,?,?,?)", ((DAY - timedelta(days=offset)).isoformat(), 55, 50, 7.5))
        activities = ((101, "running", 4.2, 28.4), (102, "volleyball", 0, 90),
                      (103, "strength_training", 0, 45), (104, "running", 5.1, 32),
                      (105, "walking", .8, 12), (106, "meditation", 0, 10))
        for identifier, sport, distance, duration in activities:
            day = DAY if identifier < 104 else DAY - timedelta(days=7)
            connection.execute("INSERT INTO activities(id,user_id,date,type,distance,duration,pace,avg_hr,max_hr,"
                               "activity_name,aerobic_effect,anaerobic_effect) VALUES(?,1,?,?,?,?,?,?,?,?,?,?)",
                               (identifier, day.isoformat(), sport, distance, duration,
                                6.75 if sport == "running" else None, 130, 155, "Invented session", 2.3, 0.2))
        connection.execute("INSERT INTO activity_laps(activity_id,lap_index,distance,duration,pace,avg_hr,avg_cadence) "
                           "VALUES(101,1,1,6.7,6.7,125,160)")
        connection.execute("INSERT INTO activity_laps(activity_id,lap_index,distance,duration,pace,avg_hr,avg_cadence) "
                           "VALUES(101,2,5.25,0.032,0.007,135,162)")
        for index in range(0, 180, 10):
            connection.execute("INSERT INTO activity_track_points(activity_id,point_index,elapsed_seconds,heart_rate) "
                               "VALUES(101,?,?,?)", (index // 10, index, 120 + index // 30))
        v2 = {"schema_version": 2, "headline": "Controlled progression.", "confidence": "medium",
              "assessment": "A steady effort.", "intent": {"planned": "easy", "detected": "steady"},
              "verdicts": [{"aspect": "Pacing", "rating": "good", "word": "Good"}],
              "worked": [{"lead": "Even start", "detail": "Built gradually."}],
              "fix": [{"lead": "Ease off", "detail": "Hold the finish."}],
              "data_notes": ["One short partial lap."],
              "sections": {"pacing": "Even splits", "aerobic": "", "recovery": "", "mental": ""},
              "recommendations": [{"text": "Try an easy run at 125 bpm", "action": "add_to_plan",
                                   "session": {"sport": "running", "intent": "easy", "duration_min": 30,
                                               "hr_cap_bpm": 125}}],
              "evidence": [{"metric": "HR", "value": "125 bpm", "source": "activity_laps.avg_hr"}]}
        legacy = {"overall_assessment": "Legacy session summary", "what_was_good": ["Stayed engaged"],
                  "brutally_honest_conclusion": "Keep this simple", "confidence": 55,
                  "pacing_analysis": "", "evidence": ["Old evidence"]}
        for identifier, payload, version in ((101, v2, "2"), (102, legacy, None)):
            connection.execute("INSERT INTO activity_coaching_insights(user_id,activity_id,summary,payload_json,"
                               "prompt_context_json,model_provider,model_name,schema_version,prompt_version,"
                               "created_at,updated_at) VALUES(1,?,?,?,?,?,?,?,?,?,?)",
                               (identifier, "Summary", json.dumps(payload), "{}", "test", "fixture", version,
                                "opinion-v2.3" if version else None, "2026-10-23 09:00", "2026-10-23 09:00"))
    return database


@pytest.fixture
def browser(activity_db):
    settings = replace(get_settings(), db_path=activity_db, llm_provider="none")
    with TestClient(create_app(settings, password="")) as client:
        yield client


def test_list_groups_filters_and_walks(browser):
    html = browser.get("/activities").text
    assert "Fri 23 Oct" in html and "Fri 16 Oct" in html
    assert html.count('class="activity-week"') == 2
    assert "/activities/101" in html and "/activities/105" not in html
    assert "/activities/106" not in html
    assert "4.2 km" in html and "28m" in html
    assert "3 sessions" in html
    assert "✓ Opinion" in html
    assert "TRIMP" in html or "Load: No data" in html
    walked = browser.get("/activities?show_walks=true").text
    assert "/activities/105" in walked and "/activities/106" not in walked
    assert "Walking" in walked
    assert "/activities/103" not in browser.get("/activities?sport=running").text
    assert "/activities/104" not in browser.get("/activities?start=2026-10-20").text


def test_list_load_more_paginates_twenty(browser, activity_db):
    with sqlite3.connect(activity_db) as connection:
        for identifier in range(200, 222):
            connection.execute("INSERT INTO activities(id,user_id,date,type,distance,duration) "
                               "VALUES(?,1,?,'running',3,20)", (identifier, DAY.isoformat()))
    first = browser.get("/activities")
    assert first.text.count('href="/activities/2') == 20
    assert 'hx-get="/activities?' in first.text
    second = browser.get("/activities?page=2", headers={"HX-Request": "true"})
    assert second.status_code == 200
    assert "activity-week" in second.text
    assert "<!doctype html>" not in second.text


@pytest.mark.parametrize("identifier,expected", [(101, "Controlled progression."), (102, "Legacy session summary"),
                                                 (103, "Gym"), (104, "Get coach opinion")])
def test_detail_renders_sports_opinions_and_missing_samples(browser, identifier, expected):
    response = browser.get(f"/activities/{identifier}")
    assert response.status_code == 200
    assert expected in response.text
    assert "Effort rating" in response.text
    assert "Ask about this" in response.text
    if identifier == 101:
        assert "Heart rate over" in response.text
        assert "5.25 m" in response.text and "Partial · excluded" in response.text
        assert "What worked" in response.text and "What to fix" in response.text
        assert "Data notes — not your mistakes" in response.text
        assert 'href="#analysis-pacing"' in response.text
        assert 'href="#analysis-aerobic"' not in response.text
        assert "Add to plan" in response.text
    if identifier in (102, 103, 104):
        assert "No data" in response.text
    if identifier in (102, 103):
        assert "Avg pace" not in response.text


def test_intent_change_does_not_regenerate_or_rewrite_opinion(browser, activity_db, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No generation on intent change")

    monkeypatch.setattr("web.routes.pages.generate_opinion", forbidden)
    with sqlite3.connect(activity_db) as connection:
        before = connection.execute("SELECT payload_json FROM activity_coaching_insights WHERE activity_id=101").fetchone()[0]
    response = browser.post("/activities/101/intent", data={"planned_intent": "tempo"},
                            headers={"HX-Request": "true"})
    assert response.status_code == 200 and "Regenerate to reassess" in response.text
    assert 'hx-trigger="change"' in response.text
    with sqlite3.connect(activity_db) as connection:
        assert connection.execute("SELECT planned_intent FROM activities WHERE id=101").fetchone()[0] == "tempo"
        assert connection.execute("SELECT payload_json FROM activity_coaching_insights WHERE activity_id=101").fetchone()[0] == before


def test_walking_detail_omits_inapplicable_effort_control(browser):
    response = browser.get("/activities/105")
    assert response.status_code == 200
    assert "Distance" in response.text
    assert 'id="activity-rating"' not in response.text


def test_regeneration_failure_keeps_opinion(browser, activity_db, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("Daily coach LLM call limit reached")

    monkeypatch.setattr("web.routes.pages.generate_opinion", fail)
    with sqlite3.connect(activity_db) as connection:
        before = connection.execute("SELECT payload_json FROM activity_coaching_insights WHERE activity_id=101").fetchone()[0]
    response = browser.post("/activities/101/opinion", data={"regenerate": "true"},
                            headers={"HX-Request": "true"})
    assert response.status_code == 200
    assert "Daily coach LLM call limit reached" in response.text
    assert "Controlled progression." in response.text
    with sqlite3.connect(activity_db) as connection:
        assert connection.execute("SELECT payload_json FROM activity_coaching_insights WHERE activity_id=101").fetchone()[0] == before


def test_add_to_plan_creates_proposal_only(browser, activity_db, monkeypatch):
    monkeypatch.setattr("coach.planning.validate_week", lambda *args, **kwargs: [])
    response = browser.post("/activities/101/recommendation/0", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/plan"
    with sqlite3.connect(activity_db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM coach_proposals").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM plan_sessions").fetchone()[0] == 0


def test_ask_passes_activity_id_and_rpe_saves(browser, activity_db, monkeypatch):
    called = []

    class Reply:
        text = "Use the first split as a guide."
        evidence = ({"metric": "HR", "display": "125 bpm"},)
        follow_ups = ("How did recovery compare?",)

    def answer(self, question, user_id, activity_id):
        called.append((question, activity_id))
        return Reply()

    monkeypatch.setattr("web.activities.TrainingChatService.answer", answer)
    response = browser.post("/activities/101/ask", data={"question": "Why?"}, headers={"HX-Request": "true"})
    assert response.status_code == 200 and "125 bpm" in response.text
    assert called == [("Why?", 101)]
    rated = browser.post("/activities/101/rate", data={"rpe": 7}, headers={"HX-Request": "true"})
    assert rated.status_code == 200 and "Rating saved: 7/10" in rated.text
    with sqlite3.connect(activity_db) as connection:
        assert connection.execute("SELECT rpe FROM activity_efforts WHERE activity_id=101").fetchone()[0] == 7
