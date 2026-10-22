"""Exact normalized type mapping; no substring heuristics."""

from datetime import date
from types import MappingProxyType

SPORTS = ("running", "volleyball", "football", "gym", "other")
SPORT_MAP = MappingProxyType({
    "running": "running", "trail_running": "running", "treadmill_running": "running",
    "treadmill": "running", "track_running": "running", "virtual_run": "running",
    "volleyball": "volleyball", "beach_volleyball": "volleyball",
    "soccer": "football", "football": "football",
    "strength_training": "gym", "indoor_cardio": "gym", "gym": "gym",
    "cycling": "other", "walking": "other", "lap_swimming": "other",
    "open_water_swimming": "other", "meditation": "other",
})


def sport_category(activity_type: str, as_of: date) -> str:
    return SPORT_MAP.get(activity_type.strip().lower(), "other")
