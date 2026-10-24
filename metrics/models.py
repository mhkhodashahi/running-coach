"""Immutable inputs and JSON-compatible dated output contracts."""

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class Provenance:
    sources: tuple[str, ...]
    window_start: str
    window_end: str
    n_days: int
    method: str


@dataclass(frozen=True)
class Metric:
    value: float | bool | None
    unit: str
    provenance: Provenance


@dataclass(frozen=True)
class Profile:
    user_id: int
    max_hr: float | None = None
    age: int | None = None


@dataclass(frozen=True)
class HealthDay:
    day: date
    resting_hr: float | None = None
    hrv: float | None = None
    sleep_duration: float | None = None


@dataclass(frozen=True)
class TrackPoint:
    index: int
    elapsed_seconds: float | None
    heart_rate: float | None
    timestamp: datetime | None = None


@dataclass(frozen=True)
class Activity:
    id: int
    day: date
    type: str
    duration: float | None
    avg_hr: float | None
    points: tuple[TrackPoint, ...] = ()
    rpe: int | None = None


@dataclass(frozen=True)
class Inputs:
    profile: Profile
    health: tuple[HealthDay, ...]
    activities: tuple[Activity, ...]


@dataclass(frozen=True)
class Baseline:
    field: str
    days: int
    mean: Metric


@dataclass(frozen=True)
class Zone:
    name: str
    seconds: Metric
    percent: Metric


@dataclass(frozen=True)
class Session:
    activity_id: int
    day: str
    sport: str
    load: Metric
    hrmax: Metric
    resting_hr: Metric
    observed_seconds: Metric
    zones: tuple[Zone, ...]


@dataclass(frozen=True)
class SportLoad:
    sport: str
    period: str
    load: Metric


@dataclass(frozen=True)
class LoadRatio:
    acute: Metric
    chronic: Metric
    ratio: Metric


@dataclass(frozen=True)
class Component:
    name: str
    score: Metric
    effective_weight: float


@dataclass(frozen=True)
class Readiness:
    score: Metric
    components: tuple[Component, ...]
    illness_flag: Metric


@dataclass(frozen=True)
class DailySnapshot:
    as_of: str
    timezone: str
    user_id: int
    baselines: tuple[Baseline, ...]
    current_health: tuple[tuple[str, Metric], ...]
    sessions: tuple[Session, ...]
    sport_loads: tuple[SportLoad, ...]
    load: LoadRatio
    readiness: Readiness
    unknown_types: tuple[str, ...]


def metric(value: float | bool | None, unit: str, sources: tuple[str, ...], start: date,
           as_of: date, n_days: int, method: str) -> Metric:
    return Metric(value, unit, Provenance(sources, start.isoformat(), as_of.isoformat(), n_days, method))
