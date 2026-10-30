"""Shared lap interpretation for activity facts and the web detail page."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, median
from typing import Any

from services.fact_display import as_number, heart_rate, pace

SPLIT_KM = 1.0
SPLIT_TOLERANCE_KM = 0.1
MIN_PACE_DISTANCE_KM = 0.05


@dataclass(frozen=True)
class InterpretedLap:
    index: int
    distance_km: float | None
    duration_min: float | None
    pace_min_km: float | None
    avg_hr: float | None
    label: str | None
    partial: bool
    distance_was_metres: bool


@dataclass(frozen=True)
class WorkoutLaps:
    laps: tuple[InterpretedLap, ...]
    structured: bool
    summary: str | None
    rep_count: int
    rep_pace: str | None
    rep_hr: str | None
    recovery_hr: str | None


def interpret_laps(laps: list[dict[str, Any]], *, running: bool,
                   session_pace: Any = None, session_hr: Any = None) -> WorkoutLaps:
    """Normalize mixed legacy lap units and identify auto-splits or workout reps."""
    prepared: list[tuple[int, float | None, float | None, float | None, float | None, str, bool]] = []
    for position, lap in enumerate(laps):
        raw_distance = as_number(lap.get("distance"))
        duration = as_number(lap.get("duration"))
        metres = bool(raw_distance is not None and (raw_distance > 10 or
                      (1 <= raw_distance <= 10 and duration is not None and duration < 1
                       and (as_number(lap.get("pace")) is None
                            or as_number(lap.get("pace")) < 1))))
        distance = raw_distance / 1000 if metres and raw_distance is not None else raw_distance
        lap_pace = as_number(lap.get("pace"))
        if (lap_pace is None or lap_pace < 1) and distance and duration and distance >= MIN_PACE_DISTANCE_KM:
            lap_pace = duration / distance
        prepared.append((int(lap.get("lap_index") or position + 1), distance, duration, lap_pace,
                         as_number(lap.get("avg_hr")), str(lap.get("lap_type") or "").strip().lower(), metres))
    def near_km(value: float | None) -> bool:
        return value is not None and abs(value - SPLIT_KM) <= SPLIT_TOLERANCE_KM

    auto_splits = running and len(prepared) >= 2 and any(near_km(item[1]) for item in prepared[:-1]) and all(
        near_km(item[1]) or (item[1] is not None and item[1] < 0.001) for item in prepared[:-1])
    structured = bool(running and len(prepared) >= 3 and not auto_splits)
    average_pace = as_number(session_pace)
    if average_pace is None and isinstance(session_pace, str) and ":" in session_pace:
        minutes, seconds = session_pace.split()[0].split(":", 1)
        average_pace = int(minutes) + int(seconds) / 60
    average_hr = as_number(session_hr)
    interpreted: list[InterpretedLap] = []
    for position, (index, distance, duration, lap_pace, hr, lap_type, metres) in enumerate(prepared):
        partial = bool(running and auto_splits and position == len(prepared) - 1
                       and distance is not None and 0 < distance < SPLIT_KM - SPLIT_TOLERANCE_KM)
        label = None
        if structured:
            if lap_type in {"work", "interval", "active", "fast", "repeat", "sprint"}:
                label = "work"
            elif lap_type in {"recovery", "rest", "easy", "warmup", "cooldown", "warm_up", "cool_down"}:
                label = "recovery"
            elif lap_pace is not None and average_pace is not None:
                label = "work" if lap_pace < average_pace * 0.95 else "recovery"
            elif hr is not None and average_hr is not None:
                label = "work" if hr > average_hr else "recovery"
        interpreted.append(InterpretedLap(index, distance, duration, lap_pace, hr, label, partial, metres))
    work_positions = [position for position, lap in enumerate(interpreted) if lap.label == "work"]
    if structured and work_positions:
        first_work, last_work = work_positions[0], work_positions[-1]
        interpreted = [InterpretedLap(lap.index, lap.distance_km, lap.duration_min, lap.pace_min_km,
                                      lap.avg_hr, "warm-up" if position < first_work else
                                      "cool-down" if position > last_work else lap.label,
                                      lap.partial, lap.distance_was_metres)
                       for position, lap in enumerate(interpreted)]
    work = [lap for lap in interpreted if lap.label == "work"]
    recovery = [lap for lap in interpreted if lap.label == "recovery"]
    rep_paces = [lap.pace_min_km for lap in work if lap.pace_min_km is not None
                 and lap.distance_km is not None and lap.distance_km >= MIN_PACE_DISTANCE_KM]
    rep_hrs = [lap.avg_hr for lap in work if lap.avg_hr is not None]
    recovery_hrs = [lap.avg_hr for lap in recovery if lap.avg_hr is not None]
    rep_pace = pace(median(rep_paces)) if rep_paces else None
    rep_hr = heart_rate(mean(rep_hrs)) if rep_hrs else None
    recovery_hr = heart_rate(mean(recovery_hrs)) if recovery_hrs else None
    durations = [lap.duration_min for lap in work if lap.duration_min is not None]
    summary = None
    if work:
        rep_duration = round(median(durations) * 60) if durations else None
        unit = f"{rep_duration} s" if rep_duration is not None and rep_duration < 60 else (
            f"{round(rep_duration / 60)} min" if rep_duration is not None else "reps")
        summary = f"{len(work)} × {unit} efforts"
        if rep_pace:
            summary += f", avg {rep_pace}"
        if rep_hr:
            summary += f" at {rep_hr}"
    return WorkoutLaps(tuple(interpreted), structured, summary, len(work), rep_pace, rep_hr, recovery_hr)
