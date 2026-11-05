"""Translate repository rows into immutable metric inputs and snapshots."""

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from db.repositories.metrics import MetricsRepository
from db.session import session_scope
from metrics.models import Activity, DailySnapshot, HealthDay, Inputs, Profile, TrackPoint
from metrics.snapshot import build_daily_snapshot


def local_day(value: str, timezone: str, as_of: date) -> date:
    if len(value) == 10:
        return date.fromisoformat(value)
    timestamp = datetime.fromisoformat(value)
    zone = ZoneInfo(timezone)
    return (timestamp.replace(tzinfo=zone) if timestamp.tzinfo is None else timestamp.astimezone(zone)).date()


def read_inputs(database: Path, user_id: int, as_of: date, timezone: str,
                point_lookback_days: int | None = 28) -> Inputs:
    zone = ZoneInfo(timezone)
    url = f"sqlite:///file:{database.resolve()}?mode=ro&uri=true"
    with session_scope(url) as session:
        repository = MetricsRepository(session)
        row = repository.profile(user_id)
        if row is None:
            raise ValueError(f"User {user_id} does not exist")
        raw_health = repository.health_rows(user_id)
        raw_activities = repository.activity_rows(user_id)
        all_efforts = repository.effort_ratings(user_id)
        dated_activities = [(row, local_day(row["date"], timezone, as_of)) for row in raw_activities]
        included = [(row, day) for row, day in dated_activities if day <= as_of]
        included_ids = {row["id"] for row, _ in included}
        efforts = {identifier: rating for identifier, rating in all_efforts.items()
                   if identifier in included_ids}
        point_ids = [row["id"] for row, day in included if
                     point_lookback_days is None
                     or day >= as_of - timedelta(days=point_lookback_days - 1)
                     or row["id"] in efforts]
        raw_points = repository.track_points(point_ids)
    profile = Profile(row["id"], row["max_hr"], row["age"])
    health = tuple(
        HealthDay(local_day(item["date"], timezone, as_of), item["resting_hr"], item["hrv"],
                  item["sleep_duration"])
        for item in raw_health
        if local_day(item["date"], timezone, as_of) <= as_of
    )
    activities = []
    for item, day in included:
        points = []
        for point in raw_points.get(item["id"], []):
            stamp = datetime.fromisoformat(point["timestamp"]) if point["timestamp"] else None
            if stamp is not None:
                stamp = stamp.replace(tzinfo=zone) if stamp.tzinfo is None else stamp.astimezone(zone)
                if stamp.date() > as_of:
                    continue
            points.append(TrackPoint(point["point_index"], point["elapsed_seconds"],
                                     point["heart_rate"], stamp))
        activities.append(Activity(item["id"], day, item["type"], item["duration"], item["avg_hr"],
                                   tuple(points), efforts.get(item["id"])))
    return Inputs(profile, health, tuple(activities))


def get_daily_snapshot(as_of: date, *, database: Path | None = None, user_id: int | None = None,
                       timezone: str | None = None, sleep_goal_hours: float | None = None,
                       hr_zones: tuple[tuple[str, int, int | None], ...] | None = None) -> DailySnapshot:
    from config import get_settings

    settings = get_settings()
    zone = timezone if timezone is not None else settings.local_timezone
    identifier = user_id if user_id is not None else settings.default_user_id
    inputs = read_inputs(database if database is not None else settings.db_path, identifier, as_of, zone)
    return build_daily_snapshot(inputs, as_of, zone,
                                sleep_goal_hours if sleep_goal_hours is not None else settings.sleep_goal_hours,
                                settings.hr_zones if hr_zones is None else hr_zones)
