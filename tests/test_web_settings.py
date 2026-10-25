"""Settings and retirement checks use invented data and a disposable DB."""

import sqlite3
from dataclasses import replace
from datetime import date
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from config import get_settings
from db.migration_runner import upgrade_database
from services.daily_decision_service import build_daily_decision
from services.import_service import ImportSummary
from web.app import create_app
from web.settings_page import save_local_config


@pytest.fixture
def settings(tmp_path):
    settings = replace(get_settings(), base_dir=tmp_path, db_path=tmp_path / "settings.db",
                       llm_provider="none", garmin_email="fixture@example.test", garmin_password="fixture")
    upgrade_database(settings.db_path)
    with sqlite3.connect(settings.db_path) as connection:
        connection.execute("INSERT INTO users(id,name,age,gender,weight,height,max_hr,marathon_goal_time,"
                           "running_goal_time) VALUES(?,?,?,?,?,?,?,?,?)",
                           (settings.default_user_id, "Fixture", 30, "unspecified", 70, 175, 190,
                            "04:00:00", "04:00:00"))
    return settings


def test_settings_profile_validates_and_saves(settings):
    with TestClient(create_app(settings, password="")) as client:
        assert client.get("/settings").status_code == 200
        response = client.post("/settings/profile", data={"name": "Sample Runner", "age": "31",
                               "gender": "other", "weight": "71.5", "height": "176", "max_hr": "192"})
        assert "Profile saved" in response.text
        assert "Check weight" in client.post("/settings/profile", data={"name": "A", "age": "30",
            "gender": "other", "weight": "0", "height": "176", "max_hr": "192"}).text
    with sqlite3.connect(settings.db_path) as connection:
        assert connection.execute("SELECT name,max_hr FROM users WHERE id=?",
                                  (settings.default_user_id,)).fetchone() == ("Sample Runner", 192)


def test_zone_and_sleep_config_only_write_named_keys(settings):
    path = settings.base_dir / ".env"
    path.write_text("KEEP_SECRET=fixture\n")
    updated = save_local_config(settings, "SLEEP_GOAL_HOURS", "8")
    assert updated.sleep_goal_hours == 8
    assert "KEEP_SECRET=fixture" in path.read_text()
    with pytest.raises(ValueError):
        save_local_config(settings, "SLEEP_GOAL_HOURS", "20")
    with TestClient(create_app(updated, password="")) as client:
        zones = {"key": "HR_ZONES"}
        for index, lower in enumerate((100, 120, 140, 160, 180), 1):
            zones[f"zone_{index}_lower"] = str(lower)
            zones[f"zone_{index}_upper"] = str(lower + 19) if index < 5 else ""
        assert "Setting saved" in client.post("/settings/config", data=zones).text
        assert "Custom bounds" in client.get("/settings").text


def test_goals_create_edit_activate_archive_and_goal_facts(settings):
    payload = {"name": "Fixture 5K", "goal_type": "5k_pb", "target_distance_km": "5",
               "target_time": "00:25:00", "target_date": "2026-11-01", "priority": "A"}
    with TestClient(create_app(settings, password="")) as client:
        assert "Goal saved" in client.post("/settings/goals", data=payload).text
        with sqlite3.connect(settings.db_path) as connection:
            goal_id = connection.execute("SELECT id FROM goals WHERE name='Fixture 5K'").fetchone()[0]
        assert "Goal updated" in client.post(f"/settings/goals/{goal_id}/activate").text
        with sqlite3.connect(settings.db_path) as connection:
            assert connection.execute("SELECT is_active FROM goals WHERE id=?", (goal_id,)).fetchone()[0] == 1
        decision = build_daily_decision(date(2026, 10, 25), settings.db_path, settings.default_user_id,
                                        settings.local_timezone, settings.sleep_goal_hours)
        assert next(fact for fact in decision.facts if fact["id"] == "ACTIVE_GOAL")["display"] == "5 km 5k pb"
        client.post("/settings/goals", data=payload | {"name": "Fixture 10K", "goal_type": "10k_pb",
                                                    "target_distance_km": "10"})
        with sqlite3.connect(settings.db_path) as connection:
            second_id = connection.execute("SELECT id FROM goals WHERE name='Fixture 10K'").fetchone()[0]
        client.post(f"/settings/goals/{second_id}/activate")
        changed = build_daily_decision(date(2026, 10, 25), settings.db_path, settings.default_user_id,
                                       settings.local_timezone, settings.sleep_goal_hours)
        assert next(fact for fact in changed.facts if fact["id"] == "ACTIVE_GOAL")["display"] == "10 km 10k pb"
        assert "Goal saved" in client.post("/settings/goals", data=payload | {"id": str(goal_id),
                                                                                  "name": "Fixture 5K race"}).text
        assert "Goal updated" in client.post(f"/settings/goals/{goal_id}/archive").text
    with sqlite3.connect(settings.db_path) as connection:
        assert connection.execute("SELECT status,is_active FROM goals WHERE id=?",
                                  (goal_id,)).fetchone() == ("archived", 0)


def test_csv_import_with_fixture_files(settings):
    with TestClient(create_app(settings, password="")) as client:
        response = client.post("/settings/import", files={
            "activities_file": ("activities.csv", BytesIO(b"activityId,activityName,startTimeLocal,activityType,distance,duration\n"
                                               b"123,Fixture Run,2026-09-22 07:00:00,running,5000,1800\n"), "text/csv"),
            "health_file": ("health.csv", BytesIO(b"date,resting_hr,hrv,sleep_duration\n2026-09-22,50,60,7.5\n"),
                            "text/csv"),
        })
        assert response.status_code == 200, response.text[:400]
        assert "Imported 1 activities and 1 health days" in response.text
    with sqlite3.connect(settings.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM health_metrics").fetchone()[0] == 1


def test_sync_runs_existing_service_and_reports_result(settings, monkeypatch):
    def fake_sync(self, session, user_id, days, health_days):
        return ImportSummary(activities_imported=2, health_rows_imported=3)
    monkeypatch.setattr("web.settings_page.GarminImportService.sync_garmin", fake_sync)
    with TestClient(create_app(settings, password="")) as client:
        response = client.post("/settings/sync")
        assert response.status_code == 200
        status = client.get("/settings/sync/status")
        assert "Imported 2 activities, 3 health days" in status.text
