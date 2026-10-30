"""Activity web routes against invented rows; no real athlete data or provider calls."""

import json
import sqlite3
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from config import get_settings
from db.migration_runner import upgrade_database
from services.daily_decision_service import build_daily_decision
from web.activities import evidence_source_label
from web.app import create_app
from web.charts import heart_rate_chart
from web.trends import trends_context

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


@pytest.mark.parametrize("path", ["/activities", "/activities/101"])
def test_activities_is_in_both_menus_and_active(browser, path):
    response = browser.get(path)
    assert response.status_code == 200
    for nav_class in ("v2-rail-links", "v2-bottom-nav"):
        nav = response.text.split(f'<nav class="{nav_class}"', 1)[1].split("</nav>", 1)[0]
        assert 'href="/activities" aria-current="page"' in nav
        assert nav.count('href="/activities"') == 1


def test_list_groups_filters_and_walks(browser):
    html = browser.get("/activities").text
    assert "Fri 23 Oct" in html and "Fri 16 Oct" in html
    assert html.count('class="v2-activity-week"') == 2
    assert "/activities/101" in html and "/activities/105" not in html
    assert "/activities/106" not in html
    assert "4.2 km" in html and "28 min" in html
    assert "3 sessions" in html
    assert html.count("Coach review") >= 2
    assert "load" in html or "No data" in html
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
    assert first.text.count('class="v2-activity-row"') == 20
    assert 'hx-get="/activities?' in first.text
    second = browser.get("/activities?page=2", headers={"HX-Request": "true"})
    assert second.status_code == 200
    assert "v2-activity-week" in second.text
    assert "<!doctype html>" not in second.text


@pytest.mark.parametrize("identifier,expected", [(101, "Controlled progression."), (102, "Legacy session summary"),
                                                 (103, "Gym"), (104, "Get a coach review")])
def test_detail_renders_sports_opinions_and_missing_samples(browser, identifier, expected):
    response = browser.get(f"/activities/{identifier}")
    assert response.status_code == 200
    assert expected in response.text
    assert "Effort rating" in response.text
    assert "Ask about this" in response.text
    if identifier == 101:
        assert "28:24" in response.text
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


def test_legacy_and_v2_opinions_mark_matching_rows_without_rewriting(browser, activity_db):
    with sqlite3.connect(activity_db) as connection:
        before = connection.execute("SELECT activity_id,payload_json FROM activity_coaching_insights "
                                    "ORDER BY activity_id").fetchall()
    for identifier, headline in ((101, "Controlled progression."), (102, "Keep this simple")):
        detail = browser.get(f"/activities/{identifier}").text
        assert headline in detail and "No coach opinion yet" not in detail
        list_html = browser.get("/activities").text
        row = list_html.split(f'href="/activities/{identifier}?from=activities"', 1)[1].split("</a>", 1)[0]
        assert "Coach review" in row
    with sqlite3.connect(activity_db) as connection:
        assert connection.execute("SELECT activity_id,payload_json FROM activity_coaching_insights "
                                  "ORDER BY activity_id").fetchall() == before


def test_selected_effort_and_effort_vs_hr_stats(browser, activity_db):
    with sqlite3.connect(activity_db) as connection:
        connection.execute("INSERT INTO activity_efforts(activity_id,rpe,rated_at,source) "
                           "VALUES(101,8,'2026-10-23 10:00','web')")
    html = browser.get("/activities/101").text
    assert 'name="rpe" value="8" aria-pressed="true"' in html
    assert 'name="rpe" value="7" aria-pressed="false"' in html
    assert "Effort vs HR" in html
    stylesheet = (Path(__file__).resolve().parents[1] / "web/static/css/v2.css").read_text()
    assert '.rating-controls button[aria-pressed="true"]{border:2px solid var(--ink);font-weight:600' in stylesheet


def test_suggestions_and_whole_session_lap_hidden(browser, activity_db):
    with sqlite3.connect(activity_db) as connection:
        connection.execute("INSERT INTO activity_laps(activity_id,lap_index,distance,duration,avg_hr) "
                           "VALUES(102,1,0,90,130)")
    run = browser.get("/activities/101").text
    team = browser.get("/activities/102").text
    assert "Compare with my best 5 km" in run
    assert "Was this harder than it looked on HR?" in team
    assert "<h2>Laps</h2>" not in team


def test_evidence_labels_are_readable_and_legacy_is_plain_list(browser):
    run = browser.get("/activities/101").text
    legacy = browser.get("/activities/102").text
    assert '<details class="opinion-evidence" open>' in run
    assert 'title="activity_laps.avg_hr"' in run
    assert "Laps</td>" in run
    assert '<ul class="legacy-evidence">' in legacy
    assert '<details class="opinion-evidence">' not in legacy
    assert run.index('class="opinion-assessment"') < run.index("What worked") < run.index("Data notes")


@pytest.mark.parametrize("source,label", [
    ("lap_analysis.laps[0].avg_hr", "Lap 1"),
    ("stream_analysis.first_half.avg_hr", "First half"),
    ("metrics_snapshot.activity_session.hr_zones[1].percent", "Heart-rate zones"),
    ("metrics_snapshot.readiness.score.value", "Readiness"),
    ("metrics_snapshot.load.ratio.value", "Load ratio"),
    ("services.hr_zones.heart_rate_zone_bounds", "Your zones"),
    ("active_goal.goal_type", "Active goal"),
])
def test_evidence_source_labels(source, label):
    assert evidence_source_label(source) == label


def test_nonrunning_opinion_action_is_hidden(browser):
    legacy = browser.get("/activities/102").text
    assert "Legacy session summary" in legacy
    assert "Get a coach review</button>" not in legacy
    gym = browser.get("/activities/103").text
    assert "Coach reviews for gym are coming soon" in gym
    assert "Get a coach review</button>" not in gym


def test_v2_activity_tabs_and_back_links_only_show_available_data(browser):
    run = browser.get("/activities/101?from=training").text
    assert 'href="/plan"' in run
    assert 'href="#activity-review"' in run
    assert 'href="#activity-laps"' in run
    assert "Read the full review" in run
    assert "Heart rate" in run
    missing = browser.get("/activities/104").text
    assert 'href="#activity-review"' not in missing
    assert 'href="#activity-laps"' not in missing
    assert "Get a coach review" in missing
    team = browser.get("/activities/102").text
    assert "Heart-rate load can miss jumps and sprints" in team


def test_insights_range_and_render_do_not_call_llm(browser, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Insights page render must not use an LLM")

    monkeypatch.setattr("web.trends.cached_trend_summary", forbidden)
    for days in (7, 28, 90):
        response = browser.get(f"/trends?range={days}")
        assert response.status_code == 200
        assert f"Last {days} days" in response.text
        assert 'aria-current="page"' in response.text
        assert "All activities" in response.text
        assert "Recovery" in response.text and "Weekly load" in response.text


def test_insights_recovery_gap_does_not_change_today_fallback(activity_db):
    missing = DAY - timedelta(days=1)
    with sqlite3.connect(activity_db) as connection:
        connection.execute("DELETE FROM health_metrics WHERE user_id=1 AND date=?", (missing.isoformat(),))
    settings = replace(get_settings(), db_path=activity_db, llm_provider="none")
    data = trends_context(settings, DAY, 7, include_summary=False)
    assert (missing.isoformat(), None) in data["series"]["readiness"]
    assert build_daily_decision(missing, activity_db, 1, settings.local_timezone,
                                settings.sleep_goal_hours, settings.hr_zones).readiness is not None


def test_structured_stride_laps_render_as_work_and_recovery(browser, activity_db):
    with sqlite3.connect(activity_db) as connection:
        connection.execute("INSERT INTO activities(id,user_id,date,type,distance,duration,pace,avg_hr) "
                           "VALUES(120,1,?,'running',2,15,6,130)", (DAY.isoformat(),))
        laps = [(1, 1.0, 6, 6, 120), (2, 80.0, .333, .004, 145),
                (3, .14, .9, 6.43, 125), (4, 82.0, .333, .004, 146),
                (5, .14, .9, 6.43, 126)]
        for index, distance, duration, lap_pace, hr in laps:
            connection.execute("INSERT INTO activity_laps(activity_id,lap_index,lap_type,distance,duration,pace,avg_hr) "
                               "VALUES(120,?,'lap',?,?,?,?)", (index, distance, duration, lap_pace, hr))
    html = browser.get("/activities/120").text
    assert "<h2>Laps</h2>" in html
    assert "2 × 20 s efforts" in html
    assert ">Work</td>" in html and ">Recovery</td>" in html
    assert "80.00 m" in html and "Partial · excluded" not in html
    assert "Avg HR (bpm)" in html and "Cadence (spm)" in html


def test_hr_chart_has_five_or_ten_minute_ticks_twenty_bpm_grid_and_zone_names():
    points = [{"elapsed_seconds": index * 10, "heart_rate": 120 + index % 30}
              for index in range(120)]
    zones = (("Z1", 100, 120), ("Z2", 120, 140), ("Z3", 140, 160),
             ("Z4", 160, 180), ("Z5", 180, 200))
    short = heart_rate_chart(points, zones, 200, 20)["svg"]
    long = heart_rate_chart(points, zones, 200, 40)["svg"]
    assert ">5 min</text>" in short and ">10 min</text>" in short
    assert ">5 min</text>" not in long and ">10 min</text>" in long
    assert ">120</text>" in short and ">140</text>" in short
    assert ">Z1</text>" in short and ">Z5</text>" in short
    assert "<title>Heart rate over" in short


@pytest.mark.parametrize("activity_id,sport,duration,expected_delta", [
    (102, "volleyball", 80, "-10 min"),
    (103, "strength_training", 40, "-5 min"),
])
def test_team_and_gym_similar_rows_show_duration_hr_and_efficiency(
        browser, activity_db, activity_id, sport, duration, expected_delta):
    with sqlite3.connect(activity_db) as connection:
        connection.execute("INSERT INTO activities(id,user_id,date,type,distance,duration,avg_hr) "
                           "VALUES(?,1,?,?,0,?,?)",
                           (activity_id + 100, (DAY - timedelta(days=50)).isoformat(), sport, duration, 120))
    html = browser.get(f"/activities/{activity_id}").text
    assert expected_delta.replace("-", "").replace("min", "min shorter") in html
    assert "10 bpm lower" in html
    assert "more efficient" not in html
    assert "load" in html
    assert ("1h 20m" if activity_id == 102 else "40 min") in html
    assert "50:07 /km" not in html
    assert "<th>Duration</th>" in html and "<th>Load</th>" not in html
    assert "<th>Status</th>" not in html


def test_running_compare_has_headers_and_relative_wording(browser, activity_db):
    with sqlite3.connect(activity_db) as connection:
        connection.execute("INSERT INTO activities(id,user_id,date,type,distance,duration,pace,avg_hr) "
                           "VALUES(220,1,?,'running',4.1,27,6.38,157)",
                           ((DAY - timedelta(days=14)).isoformat(),))
    html = browser.get("/activities/101#activity-compare").text
    for heading in ("Date", "Pace", "Avg HR", "Difference", "Status"):
        assert f"<th>{heading}</th>" in html
    assert "s/km faster" in html and "bpm higher" in html


def test_lap_time_has_no_leading_minute_zero(browser):
    html = browser.get("/activities/101#activity-laps").text
    assert ">6:42</td>" in html and ">06:42</td>" not in html
    assert "<th>Avg HR (bpm)</th>" in html and "<th>Cadence (spm)</th>" in html


def test_gym_coach_panel_has_no_distance_chip(browser):
    html = browser.get("/activities/103").text
    panel = html.split('class="v2-coach-panel"', 1)[1]
    assert "0.0 km" not in panel and "Distance" not in panel


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


def test_review_confirmation_is_secondary_and_names_provider_and_history(browser):
    html = browser.get("/activities/101").text
    assert "Get a new review" in html
    assert "Your current review will be saved in its history." in html
    assert "Provider: No provider configured." in html
    assert "coach calls remain today." in html
    assert '<input type="hidden" name="regenerate" value="true">' in html
    assert 'class="button button-primary" type="submit">Regenerate' not in html


def test_legacy_dict_section_renders_rows_not_raw_json(browser, activity_db):
    payload = {"brutally_honest_conclusion": "Start under control. Then settle.",
               "overall_assessment": "Start under control. Your pacing held.",
               "pacing_analysis": {"avg_pace": "5:58", "hr_drift": 16.4,
                                   "zone_distribution": {"Z3": 58}},
               "what_was_good": ["Stayed steady"]}
    original = json.dumps(payload)
    with sqlite3.connect(activity_db) as connection:
        connection.execute("UPDATE activity_coaching_insights SET payload_json=? WHERE activity_id=102", (original,))
    html = browser.get("/activities/102#activity-review").text
    assert "Start under control." in html and "Then settle." in html
    assert html.count("Your pacing held.") == 1
    assert "Avg pace" in html and "5:58 /km" in html
    assert "HR drift" in html and "16.4 bpm" in html
    assert "Z3" in html and "58%" in html
    assert "{&#39;" not in html and "&quot;avg_pace&quot;" not in html
    assert "<strong>Stayed steady</strong>" not in html
    assert 'class="v2-activity-head"' in html and 'id="activity-review"' in html
    with sqlite3.connect(activity_db) as connection:
        assert connection.execute("SELECT payload_json FROM activity_coaching_insights WHERE activity_id=102").fetchone()[0] == original


def test_legacy_json_text_sections_render_bullets_without_rewrite(browser, activity_db):
    payload = {"brutally_honest_conclusion": "Keep it steady.",
               "pacing_analysis": json.dumps({"zone_distribution": {"Z3": 58}, "avg_pace": "5:58"}),
               "mental_performance_insights": json.dumps(["Steady focus", "Relaxed finish"])}
    original = json.dumps(payload)
    with sqlite3.connect(activity_db) as connection:
        connection.execute("UPDATE activity_coaching_insights SET payload_json=? WHERE activity_id=102", (original,))
    html = browser.get("/activities/102#activity-review").text
    assert "Z3" in html and "58%" in html and "5:58 /km" in html
    assert "<li>Steady focus</li>" in html and "<li>Relaxed finish</li>" in html
    assert "&quot;zone_distribution&quot;" not in html
    with sqlite3.connect(activity_db) as connection:
        assert connection.execute("SELECT payload_json FROM activity_coaching_insights WHERE activity_id=102").fetchone()[0] == original


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
