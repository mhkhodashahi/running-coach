"""Code-owned workout templates and athlete-derived targets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median
from typing import Any

from services.fact_display import pace as display_pace
from services.hr_zones import heart_rate_zone_bounds

MIN_PACE_SAMPLES = 3
PACE_RANGE_SECONDS = 10
MAX_LONG_RUN_GROWTH = 1.20
QUALITY_REP_GROWTH = 1


@dataclass(frozen=True)
class WorkoutTemplate:
    id: str
    sport: str
    purpose: str
    benefit: str
    zone: str | None
    effort: str
    warmup_min: int
    cooldown_min: int
    repetitions: int
    rep_min: int
    recovery_min: int
    exercises: tuple[str, ...] = ()


TEMPLATES = {
    item.id: item for item in (
        WorkoutTemplate("recovery", "running", "Move gently while recovering.", "Recovery", "Z1", "very easy", 5, 5, 1, 20, 0),
        WorkoutTemplate("easy_base", "running", "Build aerobic consistency.", "Aerobic base", "Z2", "conversational", 5, 5, 1, 30, 0),
        WorkoutTemplate("long", "running", "Build durable easy endurance.", "Endurance", "Z2", "conversational", 10, 5, 1, 45, 0),
        WorkoutTemplate("tempo", "running", "Practice sustained controlled effort.", "Threshold endurance", "Z4", "comfortably hard", 10, 10, 3, 8, 2),
        WorkoutTemplate("threshold", "running", "Build time near threshold.", "Threshold", "Z4", "comfortably hard", 10, 10, 4, 6, 2),
        WorkoutTemplate("vo2_intervals", "running", "Practice short hard aerobic repeats.", "Aerobic power", "Z5", "hard", 10, 10, 5, 3, 3),
        WorkoutTemplate("speed", "running", "Improve running mechanics with brief strides.", "Speed", "Z4", "fast but relaxed", 10, 10, 6, 1, 2),
        WorkoutTemplate("strength_runners", "gym", "Build lower-body and core strength for running.", "Strength", None, "2 reps short of failure", 5, 5, 3, 10, 0, ("squat 8 reps", "hinge 8 reps", "lunge 8 per leg", "calf raise 12 reps", "plank 30 s")),
        WorkoutTemplate("upper_core", "gym", "Build upper-body and core resilience.", "Strength", None, "2 reps short of failure", 5, 5, 2, 10, 0, ("row 8 reps", "push-up 8 reps", "press 8 reps", "side plank 30 s per side")),
        WorkoutTemplate("mobility", "mobility", "Restore comfortable range of motion.", "Mobility", None, "gentle", 0, 0, 1, 15, 0, ("hip mobility 5 min", "ankle mobility 5 min", "thoracic rotation 5 min")),
    )
}

WORKOUT_TITLES = {
    "recovery": "Recovery run", "easy_base": "Easy run", "long": "Long run",
    "tempo": "Tempo run", "threshold": "Threshold run", "vo2_intervals": "VO2 max intervals",
    "speed": "Speed session", "strength_runners": "Strength for runners",
    "upper_core": "Upper body and core", "mobility": "Mobility",
}


def workout_title(template_id: str, duration_min: int | None = None) -> str:
    title = WORKOUT_TITLES.get(template_id, template_id.replace("_", " ").title())
    return f"{title} {duration_min} min" if duration_min is not None else title


def zone_targets(zones: tuple[tuple[str, int, int | None], ...],
                 max_hr: int | None) -> dict[str, tuple[int, int | None]]:
    """Use custom zones first; without a profile, never invent HR limits."""
    if zones:
        return {f"Z{index}": (low, high) for index, (_, low, high) in enumerate(zones, start=1)}
    if max_hr is None:
        return {}
    return {f"Z{index}": (round(low), round(high) if high != float("inf") else None)
            for index, (_, low, high) in enumerate(heart_rate_zone_bounds(max_hr), start=1)}


def pace_targets(samples: list[tuple[float, float]],
                 zones: dict[str, tuple[int, int | None]]) -> dict[str, str]:
    """Median of recent measured pace at HR in each zone; sparse zones are omitted."""
    result = {}
    for name, (low, high) in zones.items():
        values = [pace for pace, hr in samples if pace > 0 and hr >= low and (high is None or hr < high)]
        if len(values) >= MIN_PACE_SAMPLES:
            middle = median(values) * 60
            slower = display_pace((middle + PACE_RANGE_SECONDS) / 60)
            faster = display_pace(max(1, middle - PACE_RANGE_SECONDS) / 60)
            result[name] = f"{faster}–{slower}"
    return result


def goal_phase(start: date, target: date | None) -> tuple[str, int | None]:
    if target is None or target < start:
        return "maintenance", None
    weeks = max(0, (target - start).days // 7)
    return ("taper" if weeks <= 2 else "sharpen" if weeks <= 5 else
            "build" if weeks <= 12 else "base"), weeks


def race_paces(efforts: list[tuple[float, float]], goal: tuple[float, float] | None = None
               ) -> dict[str, str]:
    """Use a measured whole race within five percent, else the active goal time."""
    result = {}
    for distance in (5, 10):
        actual = [minutes / km for km, minutes in efforts if km > 0 and
                  abs(km - distance) / distance <= .05 and minutes > 0]
        if actual:
            result[f"{distance}K"] = display_pace(min(actual)) or ""
        elif goal and abs(goal[0] - distance) / distance <= .05 and goal[1] > 0:
            result[f"{distance}K"] = display_pace(goal[1] / goal[0]) or ""
    return result


def build_workout(template_id: str, duration_min: int, *, zones: dict[str, tuple[int, int | None]],
                  paces: dict[str, str], estimated_load: float | None = None,
                  why_day: str = "Fits between harder sessions.",
                  race_targets: dict[str, str] | None = None,
                  max_duration_min: int | None = None) -> dict[str, Any]:
    """Keep the prescribed total and all numeric targets in code, not model prose."""
    template = TEMPLATES[template_id]
    targets = zones.get(template.zone or "", (None, None))
    hr_range = f"{targets[0]}–{targets[1]} bpm" if targets[0] is not None and targets[1] is not None else None
    easy_bounds = zones.get("Z1", (None, None))
    easy_hr = (f"{easy_bounds[0]}–{easy_bounds[1]} bpm"
               if easy_bounds[0] is not None and easy_bounds[1] is not None else None)
    def steps_for(minutes: int) -> list[dict[str, Any]]:
        warm = min(template.warmup_min, max(0, minutes // 4))
        cool = min(template.cooldown_min, max(0, minutes // 4))
        active = max(1, minutes - warm - cool)
        repeats = min(template.repetitions, max(1, active // max(1, template.rep_min + template.recovery_min)))
        recovery = template.recovery_min
        work_min = max(1, (active - (repeats - 1) * recovery) // repeats)
        remaining = active - repeats * work_min - (repeats - 1) * recovery
        if cool:
            cool += remaining
        elif warm:
            warm += remaining
        else:
            work_min += remaining
        steps = []
        if warm:
            steps.append({"label": "Warm-up", "duration_min": warm, "zone": "Z1",
                          "hr_target": easy_hr, "effort": "easy"})
        steps.append({"label": "Main set", "reps": repeats, "duration_min": work_min,
                      "recovery_min": recovery, "zone": template.zone,
                      "hr_target": hr_range, "pace_target": paces.get(template.zone or ""),
                      "effort": template.effort, "exercises": list(template.exercises),
                      "rounds": repeats if template.sport == "gym" else None})
        if cool:
            steps.append({"label": "Cool-down", "duration_min": cool, "zone": "Z1",
                          "hr_target": easy_hr, "effort": "easy"})
        return steps

    steps = steps_for(duration_min)
    repeats = steps[1]["reps"] if len(steps) > 1 else steps[0]["reps"]
    shorter = max(30 if template_id == "long" else 20 if template.repetitions > 1 else 15,
                  duration_min - max(5, duration_min // 4))
    longer = duration_min + max(5, duration_min // 6)
    if max_duration_min is not None:
        longer = min(longer, max_duration_min)
    return {"type": template_id, "title": workout_title(template_id, duration_min),
            "purpose": template.purpose, "why_session": template.purpose,
            "benefit": template.benefit,
            "steps": steps, "duration_min": duration_min, "estimated_load": round(estimated_load)
            if estimated_load is not None else None, "how_it_feels": template.effort,
            "done_right_if": (f"Main set stays in {template.zone}" if template.zone else
                              "Finish with controlled form"), "why_day": why_day,
            "fallback": f"Shorten to {shorter} min or take an easy day",
            "variants": {"shorter": {"duration_min": shorter, "steps": steps_for(shorter)},
                         "longer": {"duration_min": longer, "steps": steps_for(longer)}
                         if longer > duration_min else None},
            "progression": "Add one rep next week only if recovery and the weekly limit allow it"
            if repeats > 1 else "Add up to 5 min next week only if the weekly and long-run limits allow it",
            "race_targets": race_targets or {},
            "pace_note": None if template.zone in paces else "Pace data is too thin; use HR and effort"}


def recent_pace_samples(rows: list[tuple[date, float | None, float | None]],
                        start: date) -> list[tuple[float, float]]:
    return [(pace, hr) for day, pace, hr in rows if start - timedelta(weeks=8) <= day < start
            and pace is not None and hr is not None and pace > 0]
