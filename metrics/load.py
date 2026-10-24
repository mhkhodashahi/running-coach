"""Session TRIMP, zone durations and coverage-aware load aggregation."""

from collections.abc import Mapping
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from math import exp, isfinite
from zoneinfo import ZoneInfo

from metrics.baselines import maximum_hr, resting_hr_for_session, valid
from metrics.effort import TEAM_SPORTS, Calibration, calibrate, combined_load, scaled_session_load, sport_multipliers
from metrics.models import Activity, HealthDay, LoadRatio, Profile, Session, SportLoad, metric
from metrics.models import Zone as ZoneResult
from metrics.sports import SPORTS, sport_category
from services.hr_zones import heart_rate_zone_bounds

LOAD_SOURCES = ("activities.date", "activities.type", "activities.duration", "activities.avg_hr",
                "activity_track_points.heart_rate", "activity_track_points.elapsed_seconds",
                "activity_track_points.timestamp", "users.max_hr", "users.age", "health_metrics.resting_hr")


def hr_intervals(activity: Activity, as_of: date, timezone: str) -> tuple[tuple[float, float], ...]:
    """Left-sample HR, bounded positive intervals; no bridging across missing HR."""
    if activity.day > as_of:
        return ()
    zone = ZoneInfo(timezone)
    cutoff = datetime.combine(as_of + timedelta(days=1), time.min, zone).timestamp()
    points = []
    for point in sorted(activity.points, key=lambda p: p.index):
        stamp = point.timestamp
        instant = (stamp.replace(tzinfo=zone) if stamp.tzinfo is None else stamp).timestamp() if stamp else None
        if instant is not None and instant >= cutoff:
            continue
        points.append((point, instant))
    result = []
    for index, (point, instant) in enumerate(points):
        elapsed = point.elapsed_seconds
        if not valid(point.heart_rate, as_of):
            continue
        if index + 1 < len(points):
            following, next_instant = points[index + 1]
            if instant is not None and next_instant is not None:
                seconds = next_instant - instant
            elif elapsed is not None and following.elapsed_seconds is not None:
                seconds = following.elapsed_seconds - elapsed
            else:
                continue
        elif elapsed is not None and valid(activity.duration, as_of):
            seconds = activity.duration * 60 - elapsed
        else:
            continue
        if instant is not None:
            seconds = min(seconds, cutoff - instant)
        if elapsed is not None and valid(activity.duration, as_of):
            if elapsed < 0 or elapsed >= activity.duration * 60:
                continue
            seconds = min(seconds, activity.duration * 60 - elapsed)
        if isfinite(seconds) and 0 < seconds <= 300:
            result.append((seconds, point.heart_rate))
    return tuple(result)


def banister_trimp(minutes: float, heart_rate: float, resting_hr: float, max_hr: float, as_of: date) -> float | None:
    if not all(isfinite(v) for v in (minutes, heart_rate, resting_hr, max_hr)) or minutes <= 0 or max_hr <= resting_hr or heart_rate <= 0:
        return None
    reserve = (heart_rate - resting_hr) / (max_hr - resting_hr)
    # Reject corrupt extreme HR instead of overflowing the exponential.
    if heart_rate > 300 or resting_hr <= 0 or 1.92 * reserve > 700:
        return None
    result = minutes * reserve * 0.64 * exp(1.92 * reserve)
    return result if isfinite(result) else None


def session_metrics(activity: Activity, profile: Profile, health: tuple[HealthDay, ...], as_of: date,
                    timezone: str, calibration: Calibration | None = None,
                    multipliers: Mapping[str, float] | None = None) -> Session | None:
    if activity.day > as_of or sport_category(activity.type, as_of) in ("excluded", "mobility"):
        return None
    session_day = activity.day
    maximum = maximum_hr(profile, session_day)
    resting = resting_hr_for_session(health, session_day)
    intervals = hr_intervals(activity, as_of, timezone)
    method = "track_points_left_sample_max_gap_300s" if intervals else "avg_hr_duration_fallback"
    load = None
    if maximum.value is not None and resting.value is not None:
        if intervals:
            parts = [banister_trimp(seconds / 60, hr, resting.value, maximum.value, session_day) for seconds, hr in intervals]
            if all(part is not None for part in parts):
                load = sum(parts)
        elif valid(activity.avg_hr, as_of) and valid(activity.duration, as_of):
            load = banister_trimp(activity.duration, activity.avg_hr, resting.value, maximum.value, session_day)
    sport = sport_category(activity.type, as_of)
    load, effort_method = scaled_session_load(sport, load, activity.rpe, activity.duration,
                                              calibration or calibrate(()), multipliers or {})
    if effort_method not in ("trimp", "missing_hr"):
        method += ";" + effort_method
    seconds_total = sum(seconds for seconds, _ in intervals)
    zones = []
    if maximum.value is not None:
        bounds = heart_rate_zone_bounds(int(maximum.value))
        for name, lower, upper in [*bounds, ("Below Z1", 0.0, bounds[0][1])]:
            seconds = sum(dt for dt, hr in intervals if lower <= hr < upper) if intervals else None
            zones.append(ZoneResult(name,
                metric(seconds, "seconds", LOAD_SOURCES, session_day, session_day, int(bool(intervals)), "shared_hr_zone_bounds_track_intervals"),
                metric(seconds / seconds_total * 100 if seconds is not None else None, "%", LOAD_SOURCES,
                       session_day, session_day, int(bool(intervals)), "percent_of_observed_hr_seconds")))
    return Session(activity.id, session_day.isoformat(), sport,
                   metric(load, "TRIMP", LOAD_SOURCES, session_day, session_day, int(load is not None), method),
                   maximum, resting,
                   metric(seconds_total if intervals else None, "seconds", LOAD_SOURCES, session_day, session_day,
                          int(bool(intervals)), "observed_track_coverage"), tuple(zones))


def calibration_and_scales(activities: tuple[Activity, ...], profile: Profile,
                           health: tuple[HealthDay, ...], as_of: date,
                           timezone: str) -> tuple[Calibration, dict[str, float]]:
    """Use HR-backed rated sessions up to as_of to set both load scales."""
    rated: list[tuple[str, float, int, float]] = []
    for activity in activities:
        if activity.day > as_of or activity.rpe is None or activity.duration is None or activity.duration <= 0:
            continue
        base = session_metrics(replace(activity, rpe=None), profile, health, as_of, timezone)
        if base is None or base.load.value is None:
            continue
        rated.append((base.sport, base.load.value, activity.rpe, activity.duration))
    calibration = calibrate(tuple((trimp, rpe * duration) for _, trimp, rpe, duration in rated))
    if calibration.factor is None:
        return calibration, {}
    ratios = []
    for sport, trimp, rpe, duration in rated:
        if sport not in TEAM_SPORTS:
            continue
        final, _ = combined_load(sport, trimp, rpe, duration, calibration)
        if final is not None:
            ratios.append((sport, trimp, final))
    return calibration, sport_multipliers(tuple(ratios))


def daily_sport_loads(sessions: tuple[Session, ...], health: tuple[HealthDay, ...], as_of: date,
                      excluded_days: frozenset[date] = frozenset()) -> tuple[SportLoad, ...]:
    results = []
    health_days = {row.day for row in health if row.day <= as_of}
    for offset in range(27, -1, -1):
        day = as_of - timedelta(days=offset)
        day_sessions = [s for s in sessions if s.day == day.isoformat()]
        observed = day in health_days or day in excluded_days or bool(day_sessions)
        for sport in SPORTS:
            selected = [s for s in day_sessions if s.sport == sport]
            known = observed and all(s.load.value is not None for s in selected)
            value = sum(s.load.value for s in selected) if known else None
            results.append(SportLoad(sport, "daily", metric(value, "TRIMP", (*LOAD_SOURCES, "health_metrics.date"),
                day, day, int(known), "session_sum; no_session_on_observed_day_assumed_rest")))
    return tuple(results)


def weekly_sport_loads(daily: tuple[SportLoad, ...], as_of: date) -> tuple[SportLoad, ...]:
    results = []
    for offset in (21, 14, 7, 0):
        end = as_of - timedelta(days=offset)
        start = end - timedelta(days=6)
        for sport in SPORTS:
            entries = [d.load for d in daily if d.sport == sport and start.isoformat() <= d.load.provenance.window_end <= end.isoformat()]
            values = [m.value for m in entries if m.value is not None]
            results.append(SportLoad(sport, "weekly", metric(sum(values) if values else None, "TRIMP", LOAD_SOURCES,
                start, end, len(values), "sum_known_days_only; missing_days_not_imputed")))
    return tuple(results)


def load_ratio(daily: tuple[SportLoad, ...], as_of: date) -> LoadRatio:
    known: dict[str, float] = {}
    for offset in range(28):
        day = (as_of - timedelta(days=offset)).isoformat()
        entries = [d.load.value for d in daily if d.period == "daily" and d.load.provenance.window_end == day]
        if len(entries) == len(SPORTS) and all(v is not None for v in entries):
            known[day] = sum(entries)
    start7, start28 = as_of - timedelta(days=6), as_of - timedelta(days=27)
    acute_values = [v for day, v in known.items() if day >= start7.isoformat()]
    acute = sum(acute_values) if acute_values else None
    chronic = sum(known.values()) / 4 if len(known) >= 14 else None
    ratio = acute / chronic if acute is not None and chronic is not None and chronic > 0 else None
    sources = (*LOAD_SOURCES, "health_metrics.date")
    return LoadRatio(metric(acute, "TRIMP", sources, start7, as_of, len(acute_values), "7d_sum_known_complete_days"),
                     metric(chronic, "TRIMP/week", sources, start28, as_of, len(known), "28d_sum_divided_by_4; min_14_observed_complete_days"),
                     metric(ratio, "ratio", sources, start28, as_of, len(known), "acute_divided_by_chronic"))
