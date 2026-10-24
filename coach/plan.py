"""Conservative, deterministic weekly suggestions and bounded revision phrases."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from coach.decision import TEAM_SPORTS

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
SUGGESTION_ORDER = (0, 2, 5, 3, 1, 4, 6)
DEFAULT_DURATION_MIN = 30
MIN_DURATION_MIN = 20
MAX_TRAINING_DAYS = 7
MAX_WEEKLY_LOAD_INCREASE = 1.10
SPORTS = ("running", "gym", *TEAM_SPORTS)


def monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def make_session(sport: str, *, duration_min: int = DEFAULT_DURATION_MIN,
                 hr_cap_bpm: int | None = None, fixed: bool = False) -> dict[str, Any]:
    if sport not in SPORTS or not MIN_DURATION_MIN <= duration_min <= 240:
        raise ValueError("Choose running, gym, football or volleyball, with a duration of 20-240 minutes")
    if hr_cap_bpm is not None and not 60 <= hr_cap_bpm <= 240:
        raise ValueError("HR cap must be between 60 and 240 bpm")
    intent = "easy" if sport == "running" else "light" if sport == "gym" else "skills only"
    return {"sport": sport, "intent": intent, "duration_min": duration_min,
            "hr_cap_bpm": hr_cap_bpm if sport == "running" else None, "fixed": fixed}


def draft_week(start: date, today: date, training_days: int, prior_minutes: int,
               existing: dict[str, dict[str, Any]], z2_cap_bpm: int | None,
               rest_today: bool = False, *, load_budget: float | None = None,
               load_rates: dict[str, float] | None = None) -> tuple[tuple[date, dict[str, Any]], ...]:
    """Only add easy work within prior time and a known projected-load budget."""
    if start != monday(start):
        raise ValueError("Week must start on Monday")
    if prior_minutes < MIN_DURATION_MIN:
        return ()
    remaining_days = max(0, min(training_days, MAX_TRAINING_DAYS) - len(existing))
    remaining_minutes = max(0, prior_minutes - sum(int(item["duration_min"]) for item in existing.values()))
    used_load = projected_plan_load(existing, load_rates or {}) if load_budget is not None else 0.0
    if used_load is None:
        return ()
    remaining_load = load_budget - used_load if load_budget is not None else None
    proposed = []
    for weekday in SUGGESTION_ORDER:
        if len(proposed) >= remaining_days or remaining_minutes < MIN_DURATION_MIN:
            break
        day = start + timedelta(days=weekday)
        if day < today or (rest_today and day == today) or day.isoformat() in existing:
            continue
        sport = "gym" if weekday == 3 and (load_budget is None or "gym" in (load_rates or {})) else "running"
        duration = min(DEFAULT_DURATION_MIN, remaining_minutes)
        if remaining_load is not None:
            rate = (load_rates or {}).get(sport)
            if rate is None or rate <= 0:
                continue
            duration = min(duration, int(remaining_load / rate + 1e-9))
            if duration < MIN_DURATION_MIN:
                continue
            remaining_load -= duration * rate
        proposed.append((day, make_session(sport, duration_min=duration, hr_cap_bpm=z2_cap_bpm)))
        remaining_minutes -= duration
    return tuple(proposed)


def projected_plan_load(sessions: dict[str, dict[str, Any]], load_rates: dict[str, float]) -> float | None:
    total = 0.0
    for session in sessions.values():
        rate = load_rates.get(session["sport"])
        if rate is None or rate <= 0:
            return None
        total += session["duration_min"] * rate
    return total


def interpret_revision(text: str, start: date, z2_cap_bpm: int | None) -> tuple[date, dict[str, Any] | None]:
    """Translate one clear day-level athlete request without sending it to an LLM."""
    words = text.strip().lower()
    if re.search(r"\b(?:not|don't|do not|avoid|instead of)\b", words):
        raise ValueError("Use a positive instruction, for example: make Saturday a rest day")
    if re.search(r"\b(?:hard|tempo|race|intervals?|sprints?|long run)\b", words):
        raise ValueError("Only easy running, light gym or rest can be proposed safely")
    weekdays = [index for index, name in enumerate(WEEKDAYS) if re.search(rf"\b{name}\b", words)]
    if len(weekdays) != 1:
        raise ValueError("Name one weekday, for example: make Saturday a rest day")
    day = start + timedelta(days=weekdays[0])
    sports = [sport for sport, pattern in (("running", r"\b(?:run|running)\b"),
                                          ("gym", r"\bgym\b"),
                                          ("football", r"\bfootball\b"),
                                          ("volleyball", r"\bvolleyball\b"))
              if re.search(pattern, words)]
    if re.search(r"\brest\b", words):
        if sports:
            raise ValueError("Choose rest or one sport, not both")
        return day, None
    if len(sports) != 1:
        raise ValueError("Ask for one sport or rest, for example: put an easy run on Thursday")
    return day, make_session(sports[0], hr_cap_bpm=z2_cap_bpm)
