"""Health windows exclude the assessment day; no imputation."""

from datetime import date, timedelta
from math import isfinite
from statistics import mean

from metrics.models import Baseline, HealthDay, Metric, Profile, metric

FIELDS = {"resting_hr": "bpm", "hrv": "ms", "sleep_duration": "hours"}


def valid(value: float | None, as_of: date) -> bool:
    return value is not None and isfinite(value) and value > 0


def health_baseline(health: tuple[HealthDay, ...], field: str, days: int, as_of: date) -> Baseline:
    if days not in (7, 28) or field not in FIELDS:
        raise ValueError("Supported baselines: resting_hr, hrv, sleep_duration; 7 or 28 days")
    start, end = as_of - timedelta(days=days), as_of - timedelta(days=1)
    daily: dict[date, list[float]] = {}
    for row in health:
        value = getattr(row, field)
        usable = valid(value, as_of) or (field == "sleep_duration" and value == 0)
        if start <= row.day <= end and usable:
            daily.setdefault(row.day, []).append(value)
    values = [mean(items) for items in daily.values()]
    result = mean(values) if len(values) >= (4 if days == 7 else 14) else None
    return Baseline(field, days, metric(result, FIELDS[field], (f"health_metrics.{field}", "health_metrics.date"),
                                      start, end, len(values), "daily_mean_then_window_mean"))


def current_health(health: tuple[HealthDay, ...], field: str, as_of: date) -> Metric:
    values = [getattr(row, field) for row in health if row.day == as_of and (
        valid(getattr(row, field), as_of) or (field == "sleep_duration" and getattr(row, field) == 0))]
    return metric(mean(values) if values else None, FIELDS[field], (f"health_metrics.{field}", "health_metrics.date"),
                  as_of, as_of, int(bool(values)), "assessment_day_only")


def recent_hrv(health: tuple[HealthDay, ...], as_of: date) -> Metric:
    """Mean of distinct nights in the three-day window ending on as_of."""
    start = as_of - timedelta(days=2)
    daily: dict[date, list[float]] = {}
    for row in health:
        if start <= row.day <= as_of and valid(row.hrv, as_of):
            daily.setdefault(row.day, []).append(row.hrv)
    values = [mean(items) for items in daily.values()]
    return metric(mean(values) if len(values) >= 2 else None, "ms",
                  ("health_metrics.hrv", "health_metrics.date"), start, as_of, len(values),
                  "last_3_nights_mean_min_2")


def resting_hr_for_session(health: tuple[HealthDay, ...], as_of: date) -> Metric:
    baseline = health_baseline(health, "resting_hr", 7, as_of).mean
    if baseline.value is not None:
        return baseline
    rows = [row for row in health if row.day <= as_of and valid(row.resting_hr, as_of)]
    latest = max((row.day for row in rows), default=as_of)
    values = [row.resting_hr for row in rows if row.day == latest]
    return metric(mean(values) if values else None, "bpm", ("health_metrics.resting_hr", "health_metrics.date"),
                  latest, latest, int(bool(values)), "latest_known_rhr_fallback")


def maximum_hr(profile: Profile, as_of: date) -> Metric:
    value = profile.max_hr if valid(profile.max_hr, as_of) else None
    method = "users.max_hr_current_profile"
    if value is None and profile.age is not None and 0 < profile.age < 120:
        value, method = 220 - profile.age, "220_minus_age_current_profile"
    return metric(value, "bpm", ("users.max_hr", "users.age"), as_of, as_of, int(value is not None), method)
