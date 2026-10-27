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
from web.view_models.training import coach_summary, percentage, selected_groups, week_view


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
    assert "No data (Synced 09:00)" in coach_summary(week)[0]


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
