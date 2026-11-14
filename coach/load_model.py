"""Shared training-load reference and estimates; independent of planning and AI."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from coach.decision import WEEKLY_LIMIT_PCT
from coach.plan import monday
from config import Settings
from db.repositories.planning import PlanningRepository
from db.session import session_scope
from metrics.calculation_scope import memoized_calculation
from metrics.load import calibration_and_scales, session_metrics
from metrics.reader import read_inputs
from metrics.sports import sport_category

MAX_WEEKLY_INCREASE = WEEKLY_LIMIT_PCT / 100
USUAL_WEEK_COUNT = 8
MIN_USUAL_WEEKS = 4

@dataclass(frozen=True)
class LoadModel:
    previous_weekly_average: float | None
    rates: dict[tuple[str, str], float]
    sport_rates: dict[str, float]
    imputed_sessions: int = 0
    expected_walking_weekly: float = 0.0
    reference_weeks: tuple[tuple[str, float], ...] = ()
    recorded_week_dates: tuple[str, ...] = ()

    @property
    def cap(self) -> float | None:
        return (self.previous_weekly_average * MAX_WEEKLY_INCREASE
                if self.previous_weekly_average is not None else None)

    @property
    def highest_recent_weekly(self) -> float | None:
        return max((load for _, load in self.reference_weeks), default=None)


def weekly_load_reference(rows: list[tuple[date, str, float | None]], cutoff: date,
                          limit: int | None = USUAL_WEEK_COUNT
                          ) -> tuple[tuple[str, float], ...]:
    """Last eight complete recorded training weeks, excluding walking and missing-load weeks."""
    totals: dict[date, float] = {}
    unknown: set[date] = set()
    for day, sport, load in rows:
        week = day - timedelta(days=day.weekday())
        if week >= cutoff or sport in ("walking", "excluded", "mobility"):
            continue
        totals[week] = totals.get(week, 0.0) + (load or 0.0)
        if load is None:
            unknown.add(week)
    selected = [(week.isoformat(), totals[week]) for week in sorted(totals, reverse=True)
                if week not in unknown]
    if limit is not None:
        selected = selected[:limit]
    return tuple(selected)


def usual_week(recorded: tuple[tuple[str, float], ...]) -> float | None:
    """Median of the latest eight complete training weeks; empty weeks are absent."""
    recent = recorded[:USUAL_WEEK_COUNT]
    return median(load for _, load in recent) if len(recent) >= MIN_USUAL_WEEKS else None


def is_recovery_item(session: dict[str, Any]) -> bool:
    return session["sport"] == "mobility"


def estimate_load(session: dict[str, Any], model: LoadModel) -> float | None:
    if is_recovery_item(session):
        return 0.0
    rate = model.rates.get((session["sport"], session["intent"]))
    if rate is None:
        rate = model.sport_rates.get(session["sport"])
    return float(session["duration_min"]) * rate if rate is not None else None


@memoized_calculation
def load_model(database: Path, user_id: int, start: date, settings: Settings) -> LoadModel:
    """Own TRIMP/min; cap uses eight completed nonempty training weeks."""
    today = datetime.now(ZoneInfo(settings.local_timezone)).date()
    end = min(start - timedelta(days=1), today)
    cutoff = min(start, monday(today))
    with session_scope(f"sqlite:///{database.resolve()}") as session:
        intents = PlanningRepository(session).planned_intents(user_id, end)
    inputs = read_inputs(database, user_id, end, settings.local_timezone, point_lookback_days=None)
    calibration, multipliers = calibration_and_scales(inputs.activities, inputs.profile,
                                                     inputs.health, end, settings.local_timezone)
    grouped: dict[tuple[str, str], list[float]] = {}
    sport_grouped: dict[str, list[float]] = {}
    rated_sport_grouped: dict[str, list[float]] = {}
    rated_intent_grouped: dict[tuple[str, str], list[float]] = {}
    measured: dict[int, float | None] = {}
    for activity in inputs.activities:
        if activity.duration is None or activity.duration <= 0:
            continue
        item = session_metrics(activity, inputs.profile, inputs.health, end, settings.local_timezone,
                               calibration, multipliers)
        if item is None:
            continue
        measured[activity.id] = item.load.value
        if item.load.value is None:
            continue
        sport = sport_category(activity.type, end)
        base = session_metrics(replace(activity, rpe=None), inputs.profile, inputs.health,
                               end, settings.local_timezone)
        rate = (base.load.value if base and base.load.value is not None else item.load.value) / activity.duration
        intent = intents.get(activity.id) or ("training" if sport in ("football", "volleyball") else "easy")
        grouped.setdefault((sport, intent), []).append(rate)
        sport_grouped.setdefault(sport, []).append(rate)
        if activity.rpe is not None:
            rated_rate = item.load.value / activity.duration
            rated_sport_grouped.setdefault(sport, []).append(rated_rate)
            rated_intent_grouped.setdefault((sport, intent), []).append(rated_rate)
    rates = {key: median(values) for key, values in grouped.items()}
    for key, values in rated_intent_grouped.items():
        if calibration.factor is not None and key[0] in ("gym", "football", "volleyball") and len(values) >= 3:
            rates[key] = median(values)
    sport_rates = {key: median(values) for key, values in sport_grouped.items()}
    for sport, values in rated_sport_grouped.items():
        if calibration.factor is not None and sport in ("gym", "football", "volleyball") and len(values) >= 3:
            sport_rates[sport] = median(values)
            for key in tuple(rates):
                if key[0] == sport and len(rated_intent_grouped.get(key, ())) < 3:
                    del rates[key]
    imputed = 0
    walking_total = 0.0
    reference_rows = []
    for activity in inputs.activities:
        sport = sport_category(activity.type, end)
        if sport in ("excluded", "mobility"):
            continue
        load = measured.get(activity.id)
        if load is None:
            intent = intents.get(activity.id) or ("training" if sport in ("football", "volleyball") else "easy")
            rate = rates.get((sport, intent), sport_rates.get(sport))
            if rate is not None and activity.duration is not None and activity.duration > 0:
                load = activity.duration * rate
                imputed += 1
        label = "walking" if activity.type.strip().lower() == "walking" else sport
        reference_rows.append((activity.day, label, load))
        if label == "walking" and activity.day >= end - timedelta(days=27) and load is not None:
            walking_total += load
    recorded = weekly_load_reference(reference_rows, cutoff, limit=None)
    weeks = recorded[:USUAL_WEEK_COUNT]
    reference = usual_week(recorded)
    return LoadModel(reference, rates, sport_rates, imputed, walking_total / 4, weeks,
                     tuple(week for week, _ in recorded))
