"""Read-only SQLite boundary; never imports setup, sessions, migrations or LLMs."""

import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from metrics.models import Activity, DailySnapshot, HealthDay, Inputs, Profile, TrackPoint
from metrics.snapshot import build_daily_snapshot


def local_day(value: str, timezone: str, as_of: date) -> date:
    if len(value) == 10:
        return date.fromisoformat(value)
    timestamp = datetime.fromisoformat(value)
    zone = ZoneInfo(timezone)
    return (timestamp.replace(tzinfo=zone) if timestamp.tzinfo is None else timestamp.astimezone(zone)).date()


def read_inputs(database: Path, user_id: int, as_of: date, timezone: str) -> Inputs:
    zone = ZoneInfo(timezone)
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        row = connection.execute("SELECT id, max_hr, age FROM users WHERE id=?", (user_id,)).fetchone()
        if row is None:
            raise ValueError(f"User {user_id} does not exist")
        profile = Profile(row["id"], row["max_hr"], row["age"])
        health = tuple(HealthDay(local_day(r["date"], timezone, as_of), r["resting_hr"], r["hrv"], r["sleep_duration"])
                       for r in connection.execute("SELECT date, resting_hr, hrv, sleep_duration FROM health_metrics WHERE user_id=? ORDER BY date", (user_id,))
                       if local_day(r["date"], timezone, as_of) <= as_of)
        activities = []
        for row in connection.execute("SELECT id, date, type, duration, avg_hr FROM activities WHERE user_id=? ORDER BY date,id", (user_id,)).fetchall():
            day = local_day(row["date"], timezone, as_of)
            if day > as_of:
                continue
            points = []
            if day >= as_of - timedelta(days=27):
                for point in connection.execute("SELECT point_index, elapsed_seconds, heart_rate, timestamp FROM activity_track_points WHERE activity_id=? ORDER BY point_index", (row["id"],)):
                    stamp = datetime.fromisoformat(point["timestamp"]) if point["timestamp"] else None
                    if stamp is not None:
                        stamp = stamp.replace(tzinfo=zone) if stamp.tzinfo is None else stamp.astimezone(zone)
                        if stamp.date() > as_of:
                            continue
                    points.append(TrackPoint(point["point_index"], point["elapsed_seconds"], point["heart_rate"], stamp))
            activities.append(Activity(row["id"], day, row["type"], row["duration"], row["avg_hr"], tuple(points)))
    return Inputs(profile, health, tuple(activities))


def get_daily_snapshot(as_of: date, *, database: Path | None = None, user_id: int | None = None,
                       timezone: str | None = None, sleep_goal_hours: float | None = None) -> DailySnapshot:
    from config import get_settings

    settings = get_settings()
    zone = timezone if timezone is not None else settings.local_timezone
    identifier = user_id if user_id is not None else settings.default_user_id
    inputs = read_inputs(database if database is not None else settings.db_path, identifier, as_of, zone)
    return build_daily_snapshot(inputs, as_of, zone, sleep_goal_hours if sleep_goal_hours is not None else settings.sleep_goal_hours)
