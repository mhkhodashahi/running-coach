"""Milestone 5a web UI tests with invented database rows only."""

import re
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from config import get_settings
from db.migration_runner import upgrade_database
from web.app import create_app
from web.charts import load_bars, sparkline
from web.formatting import sync_time


@pytest.fixture
def web_db(tmp_path):
    database = tmp_path / "web.db"
    upgrade_database(database)
    day = datetime.now(ZoneInfo("Europe/Berlin")).date()
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO users(id,max_hr,age,marathon_goal_time,running_goal_time) "
                           "VALUES(1,190,30,'04:00:00','04:00:00')")
        for offset in range(35):
            date = day - timedelta(days=offset)
            connection.execute("INSERT INTO health_metrics(user_id,date,resting_hr,hrv,sleep_duration,body_battery) "
                               "VALUES(1,?,?,?,?,?)", (date.isoformat(), 55, 50, 7.5, 80))
        connection.execute("INSERT INTO activities(id,user_id,date,type,distance,duration,avg_hr) "
                           "VALUES(340,1,?,'running',5000,1800,140)", ((day - timedelta(days=1)).isoformat(),))
    return database


@pytest.fixture
def client(web_db):
    settings = replace(get_settings(), db_path=web_db, llm_provider="none")
    with TestClient(create_app(settings, password="")) as browser:
        yield browser


def test_today_shows_decision_recovery_and_controls(client):
    response = client.get("/")
    assert response.status_code == 200
    for word in ("Readiness", "TODAY'S DECISION", "Resting HR", "HRV", "Sleep", "Body Battery",
                 "Training load", "This week", "Recent activities", "Rate your last session", "name=\"choice\""):
        assert word in response.text
    assert "/static/js/htmx.min.js" in response.text
    coach = response.text.split('<section id="coach-card"', 1)[1].split("</section>", 1)[0]
    assert coach.index('class="coach-intro"') < coach.index('class="ranked-sports"')
    assert coach.index('class="ranked-sports"') < coach.index('class="coach-bottom"')
    assert coach.index('class="intensity-control"') < coach.index('class="coach-actions"')
    assert coach.index('class="top-pick"') < coach.index('class="coach-bottom"')
    assert "Coach: <strong>" not in coach
    assert coach.count('name="choice"') == 3
    assert "Football or volleyball: only with team training" in coach


def test_today_uses_short_dates_deltas_and_clock_badge(client, web_db):
    day = datetime.now(ZoneInfo("Europe/Berlin")).date()
    now_utc = datetime.now(UTC).replace(tzinfo=None)
    with sqlite3.connect(web_db) as connection:
        connection.execute("INSERT INTO garmin_sync_status(user_id,last_synced_at) VALUES(1,?)",
                           (now_utc.isoformat(),))
        connection.execute("UPDATE health_metrics SET resting_hr=57,hrv=47,sleep_duration=8.8 "
                           "WHERE date=?", (day.isoformat(),))
    response = client.get("/")
    assert response.status_code == 200
    assert "+2 bpm vs baseline" in response.text
    assert "-3 ms vs baseline" in response.text
    assert "+1h 18m vs baseline" in response.text
    assert "8h 48m" in response.text
    assert "Baseline 55 bpm" in response.text
    assert sync_time(now_utc.isoformat(), day, "Europe/Berlin") in response.text
    assert 'class="desktop-sync"' not in response.text
    coach = response.text.split('<section id="coach-card"', 1)[1].split("</section>", 1)[0]
    assert "Synced" not in coach


def test_provisional_badge_has_short_date_without_sync(client, web_db):
    day = datetime.now(ZoneInfo("Europe/Berlin")).date()
    with sqlite3.connect(web_db) as connection:
        connection.execute("UPDATE health_metrics SET hrv=NULL WHERE date=?", (day.isoformat(),))
    response = client.get("/")
    coach = response.text.split('<section id="coach-card"', 1)[1].split("</section>", 1)[0]
    assert "Provisional · based on" in coach
    assert 'viewBox="0 0 24 24"' in coach
    assert "last sync" not in coach.lower()


@pytest.mark.parametrize("path", ["/", "/activities", "/activities/340", "/trends", "/coach", "/plan"])
def test_routes_respond(client, path):
    assert client.get(path).status_code == 200


def test_override_stored_separately_from_decision(client, web_db):
    client.get("/")
    response = client.post("/today/choice", data={"choice": "rest"}, headers={"HX-Request": "true"})
    assert response.status_code == 200
    with sqlite3.connect(web_db) as connection:
        payload = connection.execute("SELECT payload_json FROM coaching_decisions ORDER BY id DESC LIMIT 1").fetchone()[0]
    import json

    saved = json.loads(payload)
    assert saved["athlete_choice"] == "rest"
    assert saved["decision"]["intensity"] in ("rest", "easy", "hard")
    assert "Your choice" in response.text
    assert "Back to coach" in response.text
    cleared = client.post("/today/choice", data={"choice": "clear"}, headers={"HX-Request": "true"})
    assert "Your choice" not in cleared.text


def test_rating_post_persists(client, web_db):
    response = client.post("/today/rate", data={"activity_id": 340, "rpe": 7},
                           headers={"HX-Request": "true"})
    assert response.status_code == 200
    with sqlite3.connect(web_db) as connection:
        assert connection.execute("SELECT rpe,source FROM activity_efforts WHERE activity_id=340").fetchone() == (7, "web")


def test_missing_values_show_no_data(tmp_path):
    database = tmp_path / "empty.db"
    upgrade_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO users(id,max_hr,age,marathon_goal_time,running_goal_time) "
                           "VALUES(1,190,30,'04:00:00','04:00:00')")
    settings = replace(get_settings(), db_path=database, llm_provider="none")
    with TestClient(create_app(settings, password="")) as browser:
        response = browser.get("/")
    assert response.status_code == 200
    assert "No data" in response.text


def test_optional_login(web_db):
    settings = replace(get_settings(), db_path=web_db, llm_provider="none")
    with TestClient(create_app(settings, password="secret")) as browser:
        assert browser.get("/", follow_redirects=False).headers["location"] == "/login"
        assert browser.post("/login", data={"submitted_password": "wrong"}).status_code == 401
        assert browser.post("/login", data={"submitted_password": "secret"}, follow_redirects=False).status_code == 303
        assert browser.get("/").status_code == 200


def test_templates_have_no_remote_asset_urls():
    templates = Path(__file__).resolve().parents[1] / "web" / "templates"
    for template in templates.rglob("*.html"):
        assert "http://" not in template.read_text()
        assert "https://" not in template.read_text()


def test_load_chart_distinguishes_missing_day_from_rest():
    chart = load_bars([("2026-10-01", None), ("2026-10-02", 0)], 1.0, "2026-10-03 08:00")
    assert "Thu 1 Oct: No data; 2026-10-03 08:00" in chart
    assert "Fri 2 Oct: 0.0 load" in chart


def test_sparkline_needs_two_observations_and_escapes_label():
    assert sparkline([None, 1.0], "HRV") == ""
    assert "&lt;HRV&gt;" in sparkline([1.0, 2.0], "<HRV>")
    chart = sparkline([1.0, 2.0], "HRV", "sleep", 1.5)
    assert 'stroke="var(--sleep)"' in chart
    assert 'stroke-dasharray="3 3"' in chart


def test_selected_intensity_border_has_three_to_one_contrast_in_both_themes():
    styles = Path(__file__).resolve().parents[1] / "web" / "static" / "css"
    css = (styles / "app.css").read_text()
    assert ".segmented button[aria-pressed=true]{border:2px solid var(--ink);font-weight:600}" in css
    tokens = (styles / "tokens.css").read_text()

    def luminance(color):
        channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
                  for value in channels]
        return sum(channel * weight for channel, weight in zip(linear, (0.2126, 0.7152, 0.0722), strict=True))

    for theme in (tokens.split('[data-theme="day"]')[0], tokens.split('[data-theme="day"]')[1].split(":root {")[0]):
        ink = re.search(r"--ink:(#[0-9a-f]{6})", theme).group(1)
        background = re.search(r"--surface:(#[0-9a-f]{6})", theme).group(1)
        light, dark = sorted((luminance(ink), luminance(background)), reverse=True)
        assert (light + 0.05) / (dark + 0.05) >= 3


def test_startup_rejects_database_behind_head(tmp_path):
    settings = replace(get_settings(), db_path=tmp_path / "missing.db")
    with pytest.raises(RuntimeError, match="Database needs an upgrade"):
        with TestClient(create_app(settings, password="")):
            pass
