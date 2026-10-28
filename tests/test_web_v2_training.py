"""Training v2 view-model and route checks with invented fixture data."""

import sqlite3
from dataclasses import replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from coach.proposals import create_proposal, get_proposal
from config import get_settings
from db.migration_runner import upgrade_database
from web.app import create_app
from web.view_models.today import week_day, week_strip
from web.view_models.training import coach_summary, percentage, selected_groups, training_follow_ups, week_view


def test_load_percentage_and_missing_data():
    assert percentage(55, 110) == 55
    assert percentage(None, 110) is None
    assert percentage(55, None) is None


def test_week_states_and_coach_copy():
    today = date(2026, 10, 27)
    days = []
    for offset in range(7):
        stamp = date(2026, 10, 26 + offset).isoformat() if offset < 6 else "2026-11-01"
        days.append({"date": stamp, "sessions": [], "actuals": [], "empty_label": "Nothing planned",
                     "estimated_load": 0})
    days[0]["actuals"] = [{"id": 1, "sport": "gym", "duration": "30 min", "load": 20, "rate_id": 1}]
    days[1]["sessions"] = [{"id": 2, "date": days[1]["date"], "sport": "running",
                            "intent": "tempo", "duration_min": 45, "hr_cap_bpm": 165,
                            "origin": "coach", "status": "planned"}]
    days[2]["empty_label"] = "Rest day"
    raw = {"start": "2026-10-26", "days": days, "total": 80, "actual_total": 20, "cap": 110}
    week = week_view(raw, today, "Synced 09:00")
    assert week["done_count"] == 1 and week["session_count"] == 2
    assert week["days"][0]["entries"][0]["rate_id"] == 1
    assert week["days"][0]["entries"][0]["duration"] == "30 min"
    assert week["days"][1]["today"]
    assert "Hard" in week["days"][1]["entries"][0]["badges"]
    assert week["days"][2]["empty"] == "Rest day"
    assert week["total_percent"] == 80
    summary, chips = coach_summary(week)
    assert "80% of usual" in summary and chips[1] == {"label": "Load", "value": "80% of usual"}
    week["total_percent"] = None
    assert "No data · Synced 09:00" in coach_summary(week)[0]


def test_today_and_training_share_done_and_suggested_day():
    today = date(2026, 10, 27)
    days = [{"date": date.fromordinal(today.toordinal() - today.weekday() + offset).isoformat(),
             "sessions": [], "actuals": [], "empty_label": "Nothing planned", "estimated_load": 0}
            for offset in range(7)]
    actual = {"id": 10, "date": today.isoformat(), "sport": "gym", "duration": "30 min"}
    days[1]["actuals"] = [actual]
    suggestion = {"title": "tempo run", "sport": "running", "intent": "tempo", "duration": "45 min"}
    shown = week_view({"start": days[0]["date"], "days": days, "total": 113,
                       "actual_total": 25, "cap": 110}, today, "Synced 09:00", suggestion)
    strip = week_strip(today, [], [actual], recommendation=suggestion)
    assert [(item["title"], item["done"]) for item in shown["days"][1]["entries"]] == [
        (item["title"], item["done"]) for item in strip[1]["entries"]]
    assert shown["hard_count"] == 1
    assert shown["load_status"] == "Normal"
    assert "110% safe limit" in coach_summary(shown)[0]
    assert "suggested" in coach_summary(shown)[0]
    assert all(chip["value"] != "0" for chip in coach_summary(shown)[1])


def test_training_safe_limit_and_suggestion_are_displayed_separately():
    start = date(2026, 10, 26)
    days = [{"date": date.fromordinal(start.toordinal() + offset).isoformat(), "sessions": [],
             "actuals": [], "empty_label": "Nothing planned", "estimated_load": 0} for offset in range(7)]
    suggestion = {"title": "tempo run", "sport": "running", "intent": "tempo", "duration": "45 min"}
    at_limit = week_view({"start": start.isoformat(), "days": days, "total": 110,
                          "actual_total": 0, "cap": 110, "suggested_load": 20},
                         start, "Synced 09:00", suggestion)
    assert at_limit["total_percent"] == 110
    assert at_limit["with_suggested_percent"] == 130
    summary = coach_summary(at_limit)[0]
    assert "right at the 110% safe limit" in summary
    assert "With today's tempo run: 130% of usual" in summary
    above = {**at_limit, "total_percent": 111}
    assert "above the 110% safe limit" in coach_summary(above)[0]


def test_skills_only_team_session_is_not_badged_hard():
    day = date(2026, 10, 27)
    shown = week_day(day, day, [{"date": day.isoformat(), "sport": "football", "intent": "skills only",
                                 "duration_min": 30, "status": "planned"}], [])
    assert "Hard" not in shown["entries"][0]["badges"]


@pytest.mark.parametrize("percent,status", [(79, "Below usual"), (80, "Normal"),
                                           (130, "Normal"), (131, "Above usual")])
def test_training_load_status_thresholds(percent, status):
    start = date(2026, 10, 26)
    days = [{"date": date.fromordinal(start.toordinal() + offset).isoformat(), "sessions": [],
             "actuals": [], "empty_label": "Nothing planned", "estimated_load": 0} for offset in range(7)]
    shown = week_view({"start": start.isoformat(), "days": days, "total": percent,
                       "actual_total": 0, "cap": 110}, start, "Synced 09:00")
    assert shown["load_status"] == status
    if percent > 110:
        assert shown["safe_marker"] < shown["bar_total"]


def test_followups_change_with_load_and_proposal():
    above = training_follow_ups("Above usual", True)
    assert "suggestions" in above[0]
    assert not any("lighter" in item for item in above)
    assert any("lighter" in item for item in training_follow_ups("Below usual", False))
    assert not any("lighter" in item for item in training_follow_ups("Normal", False))


def test_proposal_order_pending_before_stale(client_data):
    client, settings, today = client_data
    monday = today.fromordinal(today.toordinal() - today.weekday())
    facts = [{"id": "HABIT", "metric": "Habit", "display": "one run", "source": "fixture"}]
    def make(day, title):
        return create_proposal(settings.db_path, settings.default_user_id, "weekly_plan", title, facts,
                               [{"change_type": "add", "session": {"id": None, "date": day.isoformat(),
                                 "sport": "running", "intent": "easy", "duration_min": 30,
                                 "hr_cap_bpm": None, "notes": None, "status": "planned"},
                                 "reason": "A gentle run.", "fact_ids": ["HABIT"],
                                 "group_id": title.replace(" ", "-")}])
    stale = make(monday, "Old suggestion")
    with sqlite3.connect(settings.db_path) as connection:
        connection.execute("UPDATE coach_proposals SET status='stale' WHERE id=?", (stale["id"],))
    make(monday, "Current suggestion")
    page = client.get("/plan").text
    assert page.index("Current suggestion") < page.index("Old suggestion")
    assert "suggestion is out of date" in page and "Request a fresh one" in page


def test_group_selection_is_atomic():
    groups = [{"id": "paired", "changes": [{"id": 1}, {"id": 2}]},
              {"id": "solo", "changes": [{"id": 3}]}]
    assert selected_groups(groups, [1, 2, 3]) == (["paired", "solo"], 3)
    assert selected_groups(groups, [3]) == (["solo"], 1)
    with pytest.raises(ValueError, match="Linked changes"):
        selected_groups(groups, [1])


@pytest.fixture
def client_data(tmp_path):
    settings = replace(get_settings(), db_path=tmp_path / "training-v2.db", llm_provider="none")
    upgrade_database(settings.db_path)
    with sqlite3.connect(settings.db_path) as connection:
        connection.execute("INSERT INTO users(id,max_hr,age,marathon_goal_time,running_goal_time) "
                           "VALUES(?,?,?,?,?)", (settings.default_user_id, 190, 30, "04:00:00", "04:00:00"))
    now = datetime.now(ZoneInfo(settings.local_timezone)).date()
    with TestClient(create_app(settings, password="")) as client:
        yield client, settings, now


def test_training_page_and_navigation(client_data):
    client, _, today = client_data
    response = client.get("/plan")
    assert response.status_code == 200
    assert "Training" in response.text and "sessions done" in response.text
    assert "No data" in response.text and "About: this week" in response.text
    assert "Full chat" in response.text and "Ask next" in response.text
    assert client.get(f"/plan?start={today.isoformat()}&view=month").status_code == 200
    assert client.get("/plan?view=invalid").status_code == 400


def test_proposal_selection_and_stale_review(client_data, monkeypatch):
    client, settings, today = client_data
    monday = today.fromordinal(today.toordinal() - today.weekday())
    session = {"id": None, "date": monday.isoformat(), "sport": "running", "intent": "easy",
               "duration_min": 30, "hr_cap_bpm": 130, "notes": None, "status": "planned"}
    facts = [{"id": "HABIT", "metric": "Habit", "display": "one run", "source": "fixture"}]
    created = create_proposal(settings.db_path, settings.default_user_id, "weekly_plan",
                              "One easy run", facts,
                              [{"change_type": "add", "session": session, "reason": "Rebuild gently.",
                                "fact_ids": ["HABIT"], "group_id": "run"}])
    page = client.get("/plan").text
    assert "suggestion for this week" in page and "Apply 1 change" in page
    assert 'name="change_ids"' in page and "You can undo this later" in page
    preview = client.post(f"/plan/proposals/{created['id']}/preview",
                          data={"change_ids": str(created["changes"][0]["id"])})
    assert preview.status_code == 200 and "Selected plan:" in preview.text
    assert client.post(f"/plan/proposals/{created['id']}/apply", data={"change_ids": "999"}).status_code == 409
    assert get_proposal(settings.db_path, settings.default_user_id, created["id"])["status"] == "pending"
    accepted = []
    monkeypatch.setattr("web.routes.pages.apply_change_selection",
                        lambda settings, proposal_id, change_ids: accepted.extend(change_ids))
    response = client.post(f"/plan/proposals/{created['id']}/apply",
                           data={"change_ids": str(created["changes"][0]["id"])},
                           headers={"HX-Request": "true"})
    assert response.status_code == 200 and "v2-training-content" in response.text
    assert accepted == [created["changes"][0]["id"]]
