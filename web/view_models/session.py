"""Presentation model for an approved planned workout."""

from __future__ import annotations

import json
from typing import Any

from web.view_models.today import display_duration


def session_detail(row: dict[str, Any]) -> dict[str, Any]:
    workout = row.get("workout_json")
    if isinstance(workout, str):
        workout = json.loads(workout) if workout else None
    workout = workout if isinstance(workout, dict) else None
    return {
        "session": row,
        "title": (workout or {}).get("title") or
                 f"{row['sport'].title()} · {row['intent'].replace('_', ' ').title()}",
        "duration": display_duration(row.get("duration_min")),
        "workout": workout,
        "structured": bool(workout and workout.get("steps")),
        "shorter_available": bool((workout or {}).get("variants", {}).get("shorter")),
    }
