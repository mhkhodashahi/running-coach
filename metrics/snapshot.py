"""Pure orchestration: immutable inputs in, dated metrics out."""

from dataclasses import replace
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from metrics.baselines import FIELDS, current_health, health_baseline, recent_hrv
from metrics.effort import calibrate
from metrics.load import daily_sport_loads, load_ratio, session_metrics, weekly_sport_loads
from metrics.models import DailySnapshot, Inputs
from metrics.readiness import readiness
from metrics.sports import SPORT_MAP, sport_category


def build_daily_snapshot(inputs: Inputs, as_of: date, timezone: str, sleep_goal_hours: float) -> DailySnapshot:
    ZoneInfo(timezone)
    health = tuple(row for row in inputs.health if row.day <= as_of)
    activities = tuple(row for row in inputs.activities if row.day <= as_of)
    baselines = tuple(health_baseline(health, field, days, as_of) for field in FIELDS for days in (7, 28))
    current = {field: current_health(health, field, as_of) for field in FIELDS}
    recent = tuple(row for row in sorted(activities, key=lambda a: (a.day, a.id))
                   if row.day >= as_of - timedelta(days=27))
    pairs = []
    for row in activities:
        if row.rpe is None or row.duration is None or row.duration <= 0:
            continue
        base = session_metrics(replace(row, rpe=None), inputs.profile, health, as_of, timezone)
        if base and base.load.value is not None:
            pairs.append((base.load.value, row.rpe * row.duration))
    calibration = calibrate(tuple(pairs))
    sessions = tuple(session for row in recent
                     if (session := session_metrics(row, inputs.profile, health, as_of, timezone,
                                                    calibration)) is not None)
    excluded_days = frozenset(row.day for row in recent if sport_category(row.type, as_of) in
                             ("excluded", "mobility"))
    daily = daily_sport_loads(sessions, health, as_of, excluded_days)
    load = load_ratio(daily, as_of)
    ready = readiness(current, {(b.field, b.days): b.mean for b in baselines}, load.ratio,
                      sleep_goal_hours, as_of, hrv_recent=recent_hrv(health, as_of))
    unknown = tuple(sorted({row.type for row in activities if row.type.strip().lower() not in SPORT_MAP}))
    return DailySnapshot(as_of.isoformat(), timezone, inputs.profile.user_id, baselines, tuple(current.items()),
                         sessions, (*daily, *weekly_sport_loads(daily, as_of)), load, ready, unknown)
