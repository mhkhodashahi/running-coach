"""Shared, dated recovery and load facts for Trends and coach chat."""

from __future__ import annotations

from metrics.models import DailySnapshot
from services.coach_facts import Fact
from services.fact_display import heart_rate, hours, milliseconds, short_date


def trend_facts(latest: DailySnapshot, reference: float | None, weekly_load: float | None = None,
                first: DailySnapshot | None = None, range_days: int | None = None) -> list[Fact]:
    """Describe observed endpoints and baselines; never fill missing health days."""
    health = {key: value.value for key, value in latest.current_health}
    baselines = {(item.field, item.days): item.mean.value for item in latest.baselines}
    facts: list[Fact] = [{"id": "TRENDS_AS_OF", "metric": "Latest health day",
                         "display": short_date(latest.as_of), "source": "health_metrics.date"}]
    if range_days is not None:
        facts.append({"id": "TRENDS_RANGE", "metric": "Trend range", "display": f"{range_days} days",
                      "source": "requested trend range"})
    if first is not None and first.as_of != latest.as_of:
        facts.append({"id": "TRENDS_FROM", "metric": "First health day in range",
                      "display": short_date(first.as_of), "source": "health_metrics.date"})
    for key, label, formatter, days in (("resting_hr", "Resting HR", heart_rate, 7),
                                        ("hrv", "Overnight HRV", milliseconds, 28),
                                        ("sleep_duration", "Sleep", hours, 28)):
        for suffix, number, source in (("LATEST", health.get(key), "health_metrics"),
                                       ("BASELINE", baselines.get((key, days)), "metrics.baselines")):
            if number is not None and (display := formatter(number)) is not None:
                facts.append({"id": f"{key.upper()}_{suffix}", "metric": f"{label} {suffix.lower()}",
                              "display": display, "source": f"{source}.{key}"})
        if first is not None and first.as_of != latest.as_of:
            first_value = dict(first.current_health)[key].value
            last_value = health.get(key)
            if first_value is not None and last_value is not None:
                delta = last_value - first_value
                amount = round(delta * 60) if key == "sleep_duration" else round(delta)
                unit = "min" if key == "sleep_duration" else "ms" if key == "hrv" else "bpm"
                display = f"{'up' if amount > 0 else 'down' if amount < 0 else 'unchanged'} {abs(amount)} {unit}"
                facts.append({"id": f"{key.upper()}_CHANGE", "metric": f"{label} change",
                              "display": display, "source": f"health_metrics.{key}, dated endpoints"})
    if latest.readiness.score.value is not None:
        facts.append({"id": "READINESS", "metric": "Recovery",
                      "display": f"{round(latest.readiness.score.value)}",
                      "source": "metrics.readiness"})
    if reference is not None and reference > 0 and weekly_load is not None:
        facts.append({"id": "WEEKLY_LOAD", "metric": "Load",
                      "display": f"{weekly_load / reference * 100:.0f}% of usual",
                      "source": "metrics.daily_sport_loads / coach.planning.usual_week"})
        facts.append({"id": "WEEKLY_LIMIT", "metric": "Weekly limit", "display": "110% of usual",
                      "source": "coach.decision.WEEKLY_LIMIT_PCT"})
    elif reference is None:
        facts.append({"id": "WEEKLY_LIMIT", "metric": "Weekly limit", "display": "baseline still building",
                      "source": "coach.planning.usual_week"})
    return facts
