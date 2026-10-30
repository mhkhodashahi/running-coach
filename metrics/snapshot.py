"""Pure orchestration: immutable inputs in, dated metrics out."""

from datetime import date, timedelta
from zoneinfo import ZoneInfo

from metrics.baselines import FIELDS, current_health, health_baseline, recent_hrv
from metrics.load import calibration_and_scales, daily_sport_loads, load_ratio, session_metrics, weekly_sport_loads
from metrics.models import DailySnapshot, Inputs
from metrics.readiness import readiness
from metrics.sports import SPORT_MAP, sport_category


def build_daily_snapshot(inputs: Inputs, as_of: date, timezone: str, sleep_goal_hours: float,
                         hr_zones: tuple[tuple[str, int, int | None], ...] = ()) -> DailySnapshot:
    ZoneInfo(timezone)
    health = tuple(row for row in inputs.health if row.day <= as_of)
    activities = tuple(row for row in inputs.activities if row.day <= as_of)
    baselines = tuple(health_baseline(health, field, days, as_of) for field in FIELDS for days in (7, 28))
    current = {field: current_health(health, field, as_of) for field in FIELDS}
    recent = tuple(row for row in sorted(activities, key=lambda a: (a.day, a.id))
                   if row.day >= as_of - timedelta(days=27))
    calibration, multipliers = calibration_and_scales(activities, inputs.profile, health, as_of, timezone)
    sessions = tuple(session for row in recent
                     if (session := session_metrics(row, inputs.profile, health, as_of, timezone,
                                                    calibration, multipliers, hr_zones)) is not None)
    excluded_days = frozenset(row.day for row in recent if sport_category(row.type, as_of) in
                             ("excluded", "mobility"))
    daily = daily_sport_loads(sessions, health, as_of, excluded_days)
    load = load_ratio(daily, as_of)
    ready = readiness(current, {(b.field, b.days): b.mean for b in baselines}, load.ratio,
                      sleep_goal_hours, as_of, hrv_recent=recent_hrv(health, as_of))
    unknown = tuple(sorted({row.type for row in activities if row.type.strip().lower() not in SPORT_MAP}))
    return DailySnapshot(as_of.isoformat(), timezone, inputs.profile.user_id, baselines, tuple(current.items()),
                         sessions, (*daily, *weekly_sport_loads(daily, as_of)), load, ready, unknown)
