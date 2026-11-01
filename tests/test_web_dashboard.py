"""Synthetic dashboard data, actions, and migration checks."""

import csv
import io
import sqlite3
from dataclasses import replace
from datetime import date, timedelta

import pytest
from alembic import command
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine

from config import get_settings
from db.migration_runner import migration_config, upgrade_database
from web.app import create_app
from web.charts import dashboard_svg
from web.dashboard.charts import REGISTRY, load_source, rolling_usual_band
from web.dashboard.storage import Widget, WidgetOptions, read_widgets
from web.view_models.dashboard import dashboard_state, follow_ups, panel_summary, widget_title, widget_view

DAY = date(2026, 10, 23)


@pytest.fixture
def dashboard_db(tmp_path):
    database = tmp_path / "dashboard.db"
    upgrade_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO users(id,max_hr,age,marathon_goal_time,running_goal_time) "
                           "VALUES(1,190,30,'04:00:00','04:00:00')")
        for offset in range(40):
            day = (DAY - timedelta(days=offset)).isoformat()
            connection.execute("INSERT INTO health_metrics(user_id,date,resting_hr,hrv,sleep_duration) "
                               "VALUES(1,?,?,?,?)", (day, 55, 50, 7.5))
        connection.execute("INSERT INTO activities(id,user_id,date,type,distance,duration,pace,avg_hr) "
                           "VALUES(10,1,?,'running',5,30,6,130)", ((DAY - timedelta(days=1)).isoformat(),))
        connection.execute("INSERT INTO activities(id,user_id,date,type,distance,duration,pace,avg_hr) "
                           "VALUES(11,1,?,'strength_training',0,45,NULL,120)", (DAY.isoformat(),))
        connection.execute("INSERT INTO plan_sessions(user_id,date,sport,intent,duration_min,origin,status,"
                           "linked_activity_id,created_at,updated_at) "
                           "VALUES(1,?,'running','easy',30,'athlete','done',10,'2026-10-01','2026-10-01')",
                           ((DAY - timedelta(days=1)).isoformat(),))
        connection.execute("INSERT INTO activity_laps(activity_id,lap_index,distance,duration) "
                           "VALUES(10,1,1,5.9)")
        for index in range(11):
            connection.execute("INSERT INTO activity_track_points(activity_id,point_index,elapsed_seconds,"
                               "distance_km,heart_rate) VALUES(10,?,?,?,130)",
                               (index, index * 180, index * .5))
    return database


@pytest.fixture
def dashboard_client(dashboard_db):
    settings = replace(get_settings(), db_path=dashboard_db, llm_provider="none", hr_zones=())
    with TestClient(create_app(settings, password="")) as client:
        yield client


def test_registry_data_functions_use_invented_rows_and_gaps(dashboard_db):
    settings = replace(get_settings(), db_path=dashboard_db, llm_provider="none", hr_zones=())
    source = load_source(settings, DAY)
    assert len(REGISTRY) == 8
    for definition in REGISTRY.values():
        data = definition.data_function(source, DAY - timedelta(days=27), DAY, WidgetOptions())
        assert data.columns and isinstance(data.rows, tuple), definition.id
        assert all(row.get(data.columns[0]) for row in data.rows), definition.id
    weekly = REGISTRY["weekly_load"].data_function(source, DAY - timedelta(days=27), DAY, WidgetOptions())
    assert all(row["Status"] == "baseline still building" for row in weekly.rows)
    intensity = REGISTRY["intensity_share"].data_function(source, DAY - timedelta(days=27), DAY, WidgetOptions())
    assert intensity.rows[0]["Z1–Z2 %"] == 100
    assert intensity.rows[0]["Z3+ %"] == 0
    easy = REGISTRY["pace_vs_hr_easy"].data_function(source, DAY - timedelta(days=27), DAY, WidgetOptions())
    assert easy.rows[0]["Avg HR (bpm)"] == 130
    efforts = REGISTRY["best_efforts"].data_function(
        source, DAY - timedelta(days=27), DAY, WidgetOptions(distance_km=1))
    assert efforts.rows[0]["Time (min)"] == 6
    mix = REGISTRY["training_mix"].data_function(source, DAY - timedelta(days=27), DAY, WidgetOptions())
    assert sum(row["Gym (min)"] for row in mix.rows) == 45
    recovery = REGISTRY["recovery_trends"].data_function(source, DAY - timedelta(days=41), DAY, WidgetOptions())
    assert recovery.rows[0]["Recovery"] is None
    plans = REGISTRY["planned_vs_done"].data_function(source, DAY - timedelta(days=7), DAY, WidgetOptions())
    assert any(row["Done in plan"] == 30 for row in plans.rows)


def test_best_effort_axis_is_faster_up_and_uses_clock_time():
    chart = dashboard_svg(({"Date": "2026-10-01", "Time (min)": 6.5},
                           {"Date": "2026-10-08", "Time (min)": 5.25}),
                          ("Date", "Time (min)"), "line", "Best efforts")
    assert chart["axis_min_value"] < 5.25 < 6.5 < chart["axis_max_value"]
    assert chart["axis_high"].count(":") == 1
    assert chart["y_title"] == "Time · faster ↑"
    assert "1 Oct" in chart["axis_dates"]


def test_easy_pace_scatter_y_axis_uses_hr_data_only():
    chart = dashboard_svg(({"Date": "2026-10-01", "Pace (min/km)": 6.0, "Avg HR (bpm)": 121},
                           {"Date": "2026-10-08", "Pace (min/km)": 5.5, "Avg HR (bpm)": 128}),
                          ("Date", "Pace (min/km)", "Avg HR (bpm)"), "scatter", "Easy pace vs HR")
    assert 100 < chart["axis_min_value"] < chart["axis_max_value"] < 150
    assert chart["x_title"] == "Pace (min/km)"
    assert chart["y_title"] == "Avg HR (bpm)"


def test_usual_band_is_rolling_and_requires_history():
    history = [{"Recovery": value} for value in ([60] * 28 + [80] * 14)]
    assert rolling_usual_band(history, 13, "Recovery", 28, 3) == (None, None)
    first = rolling_usual_band(history, 28, "Recovery", 28, 3)
    later = rolling_usual_band(history, 42, "Recovery", 28, 3)
    assert first == (57.0, 63.0)
    assert later[0] > first[0]
    assert later[1] > first[1]


def test_options_reject_unknown_or_invalid():
    with pytest.raises(ValidationError):
        WidgetOptions.model_validate({"mystery": "yes"})
    with pytest.raises(ValidationError):
        WidgetOptions(range="custom", from_date=DAY, to_date=DAY - timedelta(days=1))
    with pytest.raises(ValidationError):
        Widget(chart_id="weekly_load", options=WidgetOptions(sport="running"))
    with pytest.raises(ValidationError):
        WidgetOptions(range="custom", from_date=DAY - timedelta(days=366), to_date=DAY)


def test_defaults_get_does_not_write_and_actions_persist(dashboard_client, dashboard_db):
    page = dashboard_client.get("/insights/dashboard")
    assert page.status_code == 200
    assert page.text.count('class="card v2-dashboard-widget') == 4
    with sqlite3.connect(dashboard_db) as connection:
        assert connection.execute("SELECT count(*) FROM dashboard_widgets").fetchone() == (0,)
    assert dashboard_client.post("/insights/dashboard/widgets/add", data={"chart_id": "best_efforts"}).status_code == 200
    widgets = read_widgets(dashboard_db, 1)
    assert len(widgets) == 5
    key = widgets[0].id
    assert dashboard_client.post("/insights/dashboard/widgets/edit", data={
        "key": key, "opt_title": "My recovery", "opt_range": "28", "opt_size": "full"}).status_code == 200
    assert read_widgets(dashboard_db, 1)[0].options.title == "My recovery"
    assert dashboard_client.post("/insights/dashboard/widgets/duplicate", data={"key": key}).status_code == 200
    assert len(read_widgets(dashboard_db, 1)) == 6
    assert dashboard_client.post("/insights/dashboard/widgets/down", data={"key": key}).status_code == 200
    assert read_widgets(dashboard_db, 1)[1].id == key
    assert dashboard_client.post("/insights/dashboard/widgets/up", data={"key": key}).status_code == 200
    assert read_widgets(dashboard_db, 1)[0].id == key
    assert dashboard_client.post("/insights/dashboard/widgets/remove", data={"key": key}).status_code == 200
    assert len(read_widgets(dashboard_db, 1)) == 5
    assert dashboard_client.post("/insights/dashboard/widgets/add", data={
        "chart_id": "weekly_load", "opt_sport": "running"}).status_code == 400
    assert dashboard_client.post("/insights/dashboard/widgets/add", data={
        "chart_id": "best_efforts", "opt_distance_km": "10"}).status_code == 200


def test_csv_uses_same_rows_as_table(dashboard_client, dashboard_db):
    response = dashboard_client.get("/insights/dashboard/widgets/-2/csv?range=28")
    assert response.status_code == 200
    settings = replace(get_settings(), db_path=dashboard_db, llm_provider="none", hr_zones=())
    view = widget_view(read_widgets(dashboard_db, 1)[1], load_source(settings, DAY), DAY, 28, 1, "Synced 09:00")
    records = list(csv.DictReader(io.StringIO(response.text)))
    assert len(records) == len(view["rows"])
    assert tuple(records[0]) == view["table_columns"] if records else True
    if records:
        assert records[0] == {column: str(view["table_rows"][0][column]) if view["table_rows"][0].get(column) is not None
                              else "No data" for column in view["table_columns"]}


def test_all_removed_stays_empty(dashboard_db):
    from web.dashboard.storage import save_widgets

    save_widgets(dashboard_db, 1, [])
    assert read_widgets(dashboard_db, 1) == []


def test_coach_panel_is_deterministic_and_state_based():
    views = [{"chart_id": "weekly_load", "rows": ({"% of usual": 115},)}]
    assert dashboard_state(views) == "above"
    assert "110%" in panel_summary(views)
    assert "reduce training" in follow_ups(views)[0]
    views[0]["rows"] = ({"% of usual": None},)
    assert dashboard_state(views) == "building"
    assert "still building" in panel_summary(views)


def test_titles_identify_filtered_chart_without_context():
    assert widget_title(Widget(chart_id="best_efforts", options=WidgetOptions(distance_km=10))) == (
        "Best efforts · 10 km")
    assert widget_title(Widget(chart_id="intensity_share", options=WidgetOptions(sport="gym"))) == (
        "Intensity share · Gym")


def test_migration_0014_additive_and_downgrade(tmp_path):
    database = tmp_path / "before.db"
    engine = create_engine(f"sqlite:///{database}")
    config = migration_config()
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0013_strength_sets")
    finally:
        engine.dispose()
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO users(id,marathon_goal_time,running_goal_time) "
                           "VALUES(1,'03:30:00','04:15:00')")
        before = connection.execute("SELECT * FROM users").fetchall()
    upgrade_database(database, backup_dir=tmp_path / "backups")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT * FROM users").fetchall() == before
        assert connection.execute("SELECT count(*) FROM dashboard_widgets").fetchone() == (0,)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    engine = create_engine(f"sqlite:///{database}")
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "0013_strength_sets")
    finally:
        engine.dispose()
    with sqlite3.connect(database) as connection:
        assert "dashboard_widgets" not in {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert connection.execute("SELECT * FROM users").fetchall() == before
