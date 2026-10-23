"""Invented fixtures only; never open a working athlete database."""

import json
import math
import sqlite3
import subprocess
import sys
from contextlib import closing
from dataclasses import FrozenInstanceError, asdict, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from metrics.baselines import current_health, health_baseline, maximum_hr, recent_hrv, resting_hr_for_session
from metrics.load import (
    banister_trimp,
    daily_sport_loads,
    hr_intervals,
    load_ratio,
    session_metrics,
    weekly_sport_loads,
)
from metrics.models import Activity, HealthDay, Inputs, Profile, TrackPoint, metric
from metrics.reader import get_daily_snapshot, local_day, read_inputs
from metrics.readiness import load_score, readiness
from metrics.report import compare_legacy
from metrics.snapshot import build_daily_snapshot
from metrics.sports import RECOMMENDABLE_SPORTS, sport_category

DAY = date(2026, 5, 29)
ZONE = "Europe/Berlin"
PROFILE = Profile(1, 180, 40)


def health_history(count=28):
    return tuple(HealthDay(DAY - timedelta(days=i), 60, 50, 7.5) for i in range(count, -1, -1))


def activity(identifier=1, day=DAY, kind="running", duration=10, hr=120, points=()):
    return Activity(identifier, day, kind, duration, hr, points)


@pytest.mark.parametrize("days,minimum", [(7, 4), (28, 14)])
@pytest.mark.parametrize("field,expected", [("resting_hr", 60), ("hrv", 50), ("sleep_duration", 7.5)])
def test_baseline_thresholds_windows_and_distinct_days(days, minimum, field, expected):
    rows = tuple(HealthDay(DAY - timedelta(days=i), 60, 50, 7.5) for i in range(1, minimum + 1))
    assert health_baseline(rows[:-1], field, days, DAY).mean.value is None
    result = health_baseline(rows + (rows[0], HealthDay(DAY, 100, 100, 20), HealthDay(DAY + timedelta(days=1), 100, 100, 20)), field, days, DAY).mean
    assert result.value == expected
    assert result.provenance.n_days == minimum
    assert result.provenance.window_start == (DAY - timedelta(days=days)).isoformat()
    assert result.provenance.window_end == (DAY - timedelta(days=1)).isoformat()


def test_baseline_actual_mean_and_boundary_exclusion():
    rows = tuple(HealthDay(DAY - timedelta(days=i), 50 + i) for i in range(1, 9))
    assert health_baseline(rows, "resting_hr", 7, DAY).mean.value == 54
    assert current_health(rows, "resting_hr", DAY).value is None
    assert current_health((HealthDay(DAY, sleep_duration=0),), "sleep_duration", DAY).value == 0


def test_session_hr_parameters_and_historical_rhr():
    assert maximum_hr(PROFILE, DAY).value == 180
    assert maximum_hr(Profile(1, None, 40), DAY).value == 180
    assert maximum_hr(Profile(1), DAY).value is None
    rows = (HealthDay(DAY - timedelta(days=4), 55), HealthDay(DAY + timedelta(days=1), 90))
    result = resting_hr_for_session(rows, DAY)
    assert result.value == 55
    assert result.provenance.window_end == (DAY - timedelta(days=4)).isoformat()
    assert resting_hr_for_session(health_history(), DAY).value == 60
    past = activity(day=DAY - timedelta(days=10))
    assert session_metrics(past, PROFILE, (HealthDay(DAY, 60),), DAY, ZONE).load.value is None


def test_exact_banister_and_track_vs_average_fallback():
    expected = 10 * 0.5 * 0.64 * math.exp(1.92 * 0.5)
    assert banister_trimp(10, 120, 60, 180, DAY) == pytest.approx(expected)
    reserve = (55 - 60) / (180 - 60)
    assert banister_trimp(1, 55, 60, 180, DAY) == pytest.approx(reserve * 0.64 * math.exp(1.92 * reserve))
    average = session_metrics(activity(), PROFILE, health_history(), DAY, ZONE)
    assert average.load.value == pytest.approx(expected)
    assert average.load.provenance.method == "avg_hr_duration_fallback"
    points = (TrackPoint(0, 0, 120), TrackPoint(1, 60, 150), TrackPoint(2, 120, 180))
    track = session_metrics(activity(duration=2, hr=100, points=points), PROFILE, health_history(), DAY, ZONE)
    assert track.load.value == pytest.approx(0.5 * 0.64 * math.exp(0.96) + 0.75 * 0.64 * math.exp(1.44))
    assert track.load.provenance.method.startswith("track_points")
    assert track.observed_seconds.value == 120
    assert session_metrics(activity(hr=None), PROFILE, health_history(), DAY, ZONE).load.value is None
    assert session_metrics(activity(), Profile(1), health_history(), DAY, ZONE).load.value is None
    assert session_metrics(activity(day=DAY + timedelta(days=1)), PROFILE, health_history(), DAY, ZONE) is None


def test_track_gaps_duplicates_missing_hr_and_final_tail():
    points = (TrackPoint(0, 0, 120), TrackPoint(1, 60, None), TrackPoint(2, 120, 120),
              TrackPoint(3, 120, 120), TrackPoint(4, 600, 120))
    intervals = hr_intervals(activity(duration=11, points=points), DAY, ZONE)
    assert intervals == ((60, 120), (60, 120))
    assert hr_intervals(activity(points=(TrackPoint(0, None, 120),)), DAY, ZONE) == ()


def test_zones_reuse_boundaries_and_percentages():
    points = tuple(TrackPoint(i, i * 60, hr) for i, hr in enumerate((80, 90, 108, 126, 144, 162, 180)))
    session = session_metrics(activity(duration=6, points=points), PROFILE, health_history(), DAY, ZONE)
    assert {z.name for z in session.zones} == {"Below Z1", "Z1 Recovery", "Z2 Easy", "Z3 Steady", "Z4 Threshold", "Z5 Max"}
    assert sum(z.seconds.value for z in session.zones) == 360
    for zone in session.zones:
        assert zone.seconds.value == 60
        assert zone.percent.value == pytest.approx(100 / 6)
    assert all(z.seconds.value is None for z in session_metrics(activity(), PROFILE, health_history(), DAY, ZONE).zones)


def test_timezone_and_future_track_point_cutoff():
    assert local_day("2026-05-28T23:30:00+00:00", ZONE, DAY) == DAY
    assert local_day("2026-05-29", ZONE, DAY) == DAY
    # Berlin switches to daylight saving on March 29: 01:59 -> 03:00 is one minute.
    spring = date(2026, 3, 29)
    points = (TrackPoint(0, None, 120, datetime(2026, 3, 29, 0, 59, tzinfo=UTC)),
              TrackPoint(1, None, 120, datetime(2026, 3, 29, 1, 0, tzinfo=UTC)))
    assert hr_intervals(activity(day=spring, points=points), spring, ZONE) == ((60, 120),)
    future = TrackPoint(9, 180, 220, datetime(2026, 5, 29, 22, 0, tzinfo=UTC))
    points = (TrackPoint(0, 0, 120, datetime(2026, 5, 29, 21, 58, tzinfo=UTC)),
              TrackPoint(1, 60, 120, datetime(2026, 5, 29, 21, 59, tzinfo=UTC)))
    assert hr_intervals(activity(duration=2, points=points + (future,)), DAY, ZONE) == hr_intervals(activity(duration=2, points=points), DAY, ZONE)


def test_sport_mapping_and_unknowns():
    for raw, expected in ((" RUNNING ", "running"), ("soccer", "football"), ("volleyball", "volleyball"),
                          ("strength_training", "gym"), ("walking", "other"), ("new sport", "other"),
                          ("meditation", "excluded"), ("breathwork", "excluded"),
                          ("yoga_nidra", "excluded"), ("mobility", "mobility")):
        assert sport_category(raw, DAY) == expected
    assert RECOMMENDABLE_SPORTS == ("running", "volleyball", "football", "gym")
    assert "other" not in RECOMMENDABLE_SPORTS
    assert "excluded" not in RECOMMENDABLE_SPORTS
    assert "mobility" not in RECOMMENDABLE_SPORTS
    snapshot = build_daily_snapshot(Inputs(PROFILE, (), (activity(kind="new sport"),)), DAY, ZONE, 7.5)
    assert snapshot.unknown_types == ("new sport",)


@pytest.mark.parametrize("kind", ("meditation", "breathwork", "yoga_nidra", "mobility"))
def test_excluded_activity_has_no_session_or_load(kind):
    excluded = activity(kind=kind)
    assert session_metrics(excluded, PROFILE, health_history(), DAY, ZONE) is None
    snapshot = build_daily_snapshot(Inputs(PROFILE, (), (excluded,)), DAY, ZONE, 7.5)
    assert snapshot.sessions == ()
    assert snapshot.unknown_types == ()
    today = [row for row in snapshot.sport_loads if row.period == "daily" and row.load.provenance.window_end == DAY.isoformat()]
    assert {row.sport for row in today} == {*RECOMMENDABLE_SPORTS, "other"}
    assert all(row.load.value == 0 for row in today)
    assert snapshot.load.acute.value == 0


def test_walking_contributes_to_other_load_without_being_recommendable():
    snapshot = build_daily_snapshot(Inputs(PROFILE, health_history(),
                                           (activity(kind="walking"), activity(2, kind="meditation"))), DAY, ZONE, 7.5)
    assert len(snapshot.sessions) == 1
    assert snapshot.sessions[0].sport == "other"
    assert snapshot.sessions[0].load.value is not None
    assert snapshot.sessions[0].load.value > 0
    assert "other" not in RECOMMENDABLE_SPORTS
    other_today = next(row for row in snapshot.sport_loads if row.period == "daily" and row.sport == "other"
                       and row.load.provenance.window_end == DAY.isoformat())
    assert other_today.load.value == pytest.approx(snapshot.sessions[0].load.value)


def test_acute_chronic_ratio_and_sport_sums():
    health = health_history(56)
    sessions = tuple(session_metrics(activity(identifier=i, day=DAY - timedelta(days=i), kind="soccer"), PROFILE, health, DAY, ZONE) for i in range(28))
    daily = daily_sport_loads(sessions, health, DAY)
    result = load_ratio(daily, DAY)
    single = 10 * 0.5 * 0.64 * math.exp(0.96)
    assert result.acute.value == pytest.approx(single * 7)
    assert result.chronic.value == pytest.approx(single * 7)
    assert result.ratio.value == pytest.approx(1)
    assert result.chronic.provenance.n_days == 28
    football = [row for row in weekly_sport_loads(daily, DAY) if row.sport == "football"]
    assert len(football) == 4
    assert all(row.load.value == pytest.approx(single * 7) for row in football)
    assert all(row.load.value == 0 for row in daily if row.sport == "gym")


def test_missing_history_is_not_zero_and_fourteen_day_threshold():
    empty = daily_sport_loads((), (), DAY)
    assert all(row.load.value is None for row in empty)
    assert load_ratio(empty, DAY).acute.value is None
    assert load_ratio(empty, DAY).ratio.value is None
    health = tuple(HealthDay(DAY - timedelta(days=i), 60) for i in range(14))
    assert load_ratio(daily_sport_loads((), health[:13], DAY), DAY).chronic.value is None
    assert load_ratio(daily_sport_loads((), health, DAY), DAY).chronic.value == 0
    assert load_ratio(daily_sport_loads((), health, DAY), DAY).ratio.value is None
    session = session_metrics(activity(hr=None), PROFILE, health, DAY, ZONE)
    assert load_ratio(daily_sport_loads((session,), health, DAY), DAY).chronic.value is None


@pytest.mark.parametrize("ratio,expected", [(0, 50), (0.5, 50), (0.65, 75), (0.8, 100), (1.3, 100), (1.55, 50), (1.8, 0), (2, 0), (None, None)])
def test_load_readiness_component(ratio, expected):
    result = load_score(ratio, DAY)
    assert result == pytest.approx(expected) if expected is not None else result is None


def ready(hrv=50, rhr=60, sleep=7.5, ratio=1, hrv_base=50, rhr_base=60):
    current = {name: metric(value, "test", (f"health_metrics.{name}",), DAY, DAY, int(value is not None), "fixture")
               for name, value in (("hrv", hrv), ("resting_hr", rhr), ("sleep_duration", sleep))}
    baseline = {(name, days): metric(value, "test", (f"health_metrics.{name}",), DAY - timedelta(days=days), DAY - timedelta(days=1), days, "fixture")
                for name, days, value in (("hrv", 28, hrv_base), ("resting_hr", 7, rhr_base))}
    load = metric(ratio, "ratio", ("activities.avg_hr",), DAY - timedelta(days=27), DAY, 28, "fixture")
    return readiness(current, baseline, load, 7.5, DAY, hrv_recent=current["hrv"])


def test_recent_hrv_uses_three_nights_and_needs_two_distinct_days():
    rows = (HealthDay(DAY - timedelta(days=2), hrv=40), HealthDay(DAY - timedelta(days=1), hrv=50),
            HealthDay(DAY, hrv=60), HealthDay(DAY + timedelta(days=1), hrv=100))
    result = recent_hrv(rows, DAY)
    assert result.value == 50
    assert result.provenance.n_days == 3
    assert recent_hrv(rows[:1], DAY).value is None
    assert recent_hrv((rows[0], rows[0]), DAY).provenance.n_days == 1


def test_readiness_v11_uses_smoothed_hrv_but_illness_uses_last_night():
    rows = (HealthDay(DAY - timedelta(days=2), hrv=50), HealthDay(DAY - timedelta(days=1), hrv=50),
            HealthDay(DAY, hrv=40))
    current = {name: metric(value, "test", (f"health_metrics.{name}",), DAY, DAY, 1, "fixture")
               for name, value in (("hrv", 40), ("resting_hr", 67), ("sleep_duration", 7.5))}
    baselines = {(name, days): metric(value, "test", (f"health_metrics.{name}",),
                                      DAY - timedelta(days=days), DAY - timedelta(days=1), days, "fixture")
                 for name, days, value in (("hrv", 28, 50), ("resting_hr", 7, 60))}
    ratio = metric(1, "ratio", ("activities",), DAY - timedelta(days=27), DAY, 28, "fixture")
    new = readiness(current, baselines, ratio, 7.5, DAY, hrv_recent=recent_hrv(rows, DAY), version="v1.1")
    newest = readiness(current, baselines, ratio, 7.5, DAY, hrv_recent=recent_hrv(rows, DAY))
    old = readiness(current, baselines, ratio, 7.5, DAY, version="v1")
    assert next(item.score.value for item in new.components if item.name == "hrv") == pytest.approx(40)
    assert next(item.score.value for item in newest.components if item.name == "hrv") == pytest.approx(60)
    assert next(item.score.value for item in old.components if item.name == "hrv") == pytest.approx(0)
    assert newest.illness_flag.value is True


def test_readiness_exact_components_and_reweighting():
    full = ready()
    assert full.score.value == 83.5
    assert {c.name: c.score.value for c in full.components} == {"hrv": 70, "sleep": 100, "rhr": 70, "load": 100}
    partial = ready(hrv=None, ratio=None)
    assert partial.score.value == pytest.approx((100 * 25 + 70 * 20) / 45)
    assert {c.name: c.effective_weight for c in partial.components} == {"hrv": 0, "sleep": 25 / 45, "rhr": 20 / 45, "load": 0}
    assert ready(hrv=None, rhr=None).score.value is None
    assert ready(rhr=None, sleep=None, ratio=None).score.value is None
    extreme = ready(hrv=100, rhr=100, sleep=15)
    assert {c.name: c.score.value for c in extreme.components} == {"hrv": 100, "sleep": 100, "rhr": 0, "load": 100}
    assert ready(sleep=0).components[1].score.value == 0


def test_illness_flag_on_off_and_missing():
    assert ready(hrv=42.5, rhr=67).illness_flag.value is True
    assert ready(hrv=42.6, rhr=67).illness_flag.value is False
    assert ready(hrv=42.5, rhr=66.9).illness_flag.value is False
    assert ready(hrv=None).illness_flag.value is None


def test_future_inputs_ignored_and_snapshot_json_immutable():
    source = Inputs(PROFILE, health_history(), (activity(),))
    expected = build_daily_snapshot(source, DAY, ZONE, 7.5)
    future = replace(source, health=source.health + (HealthDay(DAY + timedelta(days=1), 90, 5, 1),),
                     activities=source.activities + (activity(2, DAY + timedelta(days=1), "unknown future sport"),))
    assert build_daily_snapshot(future, DAY, ZONE, 7.5) == expected
    assert json.loads(json.dumps(asdict(expected), allow_nan=False))["as_of"] == DAY.isoformat()
    with pytest.raises(FrozenInstanceError):
        expected.as_of = "changed"


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "invented.db"
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript((Path(__file__).parents[1] / "db/migrations/baseline.sql").read_text())
        connection.execute("INSERT INTO users (id,age,max_hr,marathon_goal_time) VALUES (1,40,180,'04:00:00')")
        connection.execute("INSERT INTO users (id,age,max_hr,marathon_goal_time) VALUES (2,40,190,'04:00:00')")
        for offset in range(56):
            day = DAY - timedelta(days=offset)
            connection.execute("INSERT INTO health_metrics (user_id,date,resting_hr,hrv,sleep_duration) VALUES (1,?,60,50,7.5)", (day.isoformat(),))
        connection.execute("INSERT INTO activities (id,user_id,date,type,distance,duration,avg_hr) VALUES (1,1,?,'running',2,10,120)", (DAY.isoformat(),))
        connection.execute("INSERT INTO activities (id,user_id,date,type,distance,duration,avg_hr) VALUES (2,2,?,'private_other_user',2,10,120)", (DAY.isoformat(),))
        connection.commit()
    return path


def test_readonly_reader_scope_missing_db_and_cli(database, tmp_path):
    original = database.read_bytes()
    snapshot = get_daily_snapshot(DAY, database=database, user_id=1, timezone=ZONE)
    assert len(snapshot.sessions) == 1
    assert snapshot.unknown_types == ()
    assert snapshot.readiness.score.value is not None
    result = subprocess.run([sys.executable, "-m", "metrics.report", "--date", DAY.isoformat(), "--db", str(database), "--user-id", "1"], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)["snapshot"]["as_of"] == DAY.isoformat()
    assert database.read_bytes() == original
    missing = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        read_inputs(missing, 1, DAY, ZONE)
    assert not missing.exists()


def test_reader_local_dates_future_and_legacy_comparison(database):
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("INSERT INTO activities (id,user_id,date,type,distance,duration,avg_hr) VALUES (3,1,?,'running',2,10,120)", ("2026-05-29T22:30:00+00:00",))
        connection.commit()
    assert len(read_inputs(database, 1, DAY, ZONE).activities) == 1
    assert len(read_inputs(database, 1, DAY + timedelta(days=1), ZONE).activities) == 2
    before = database.read_bytes()
    rows = compare_legacy(database, 1, DAY, ZONE, 7.5)
    assert len(rows) == 7


    assert rows[-1]["old_7d_load_arbitrary_units"] == 9
    assert rows[-1]["new_7d_load_trimp"] == pytest.approx(10 * 0.5 * 0.64 * math.exp(.96))
    assert {"new_hrv_score", "new_rhr_score", "new_sleep_score", "new_load_score",
            "new_load_ratio", "new_illness_flag"} <= rows[-1].keys()
    snapshot = get_daily_snapshot(DAY, database=database, user_id=1, timezone=ZONE)
    assert rows[-1]["new_hrv_score"] == next(c.score.value for c in snapshot.readiness.components if c.name == "hrv")
    assert rows[-1]["new_load_ratio"] == snapshot.load.ratio.value
    assert rows[-1]["new_illness_flag"] == snapshot.readiness.illness_flag.value
    assert database.read_bytes() == before


def test_reader_planning_can_include_older_track_points(database):
    old_day = DAY - timedelta(days=40)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("INSERT INTO activities(id,user_id,date,type,distance,duration,avg_hr) "
                           "VALUES(4,1,?,'running',2,10,120)", (old_day.isoformat(),))
        connection.execute("INSERT INTO activity_track_points(activity_id,point_index,elapsed_seconds,heart_rate) "
                           "VALUES(4,0,0,120)")
        connection.commit()
    default = next(item for item in read_inputs(database, 1, DAY, ZONE).activities if item.id == 4)
    planning = next(item for item in read_inputs(database, 1, DAY, ZONE,
                                                 point_lookback_days=None).activities if item.id == 4)
    assert default.points == ()
    assert len(planning.points) == 1
