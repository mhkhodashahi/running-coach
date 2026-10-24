"""Perceived exertion load, calibrated against the athlete's HR history."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from statistics import median

MIN_CALIBRATION_SESSIONS = 5
MIN_SPORT_SCALE_SESSIONS = 3
TEAM_SPORTS = frozenset({"volleyball", "football", "gym"})


@dataclass(frozen=True)
class Calibration:
    factor: float | None
    rated_hr_sessions: int
    method: str


def srpe_load(rpe: int, duration_min: float) -> float:
    if isinstance(rpe, bool) or not isinstance(rpe, int) or not 0 <= rpe <= 10:
        raise ValueError("RPE must be an integer from 0 to 10")
    if duration_min < 0:
        raise ValueError("Duration must be nonnegative")
    return rpe * duration_min


def calibrate(pairs: tuple[tuple[float, float], ...]) -> Calibration:
    ratios = [trimp / srpe for trimp, srpe in pairs if trimp >= 0 and srpe > 0]
    if len(ratios) < MIN_CALIBRATION_SESSIONS:
        return Calibration(None, len(ratios), "insufficient_rated_hr_sessions")
    return Calibration(median(ratios), len(ratios), "median_hr_trimp_per_srpe")


def combined_load(sport: str, trimp: float | None, rpe: int | None,
                  duration_min: float | None, calibration: Calibration) -> tuple[float | None, str]:
    if sport not in TEAM_SPORTS or rpe is None or duration_min is None or calibration.factor is None:
        return trimp, "trimp" if trimp is not None else "missing_hr"
    perceived = calibration.factor * srpe_load(rpe, duration_min)
    return (max(trimp, perceived) if trimp is not None else perceived,
            "max_trimp_calibrated_srpe" if trimp is not None else "calibrated_srpe_no_hr")


def sport_multipliers(rated_hr_loads: tuple[tuple[str, float, float], ...]) -> dict[str, float]:
    """Median rated final-load/TRIMP ratio once a sport has three HR-backed ratings."""
    grouped: dict[str, list[float]] = {}
    for sport, trimp, final_load in rated_hr_loads:
        if sport in TEAM_SPORTS and trimp > 0 and final_load >= trimp:
            grouped.setdefault(sport, []).append(final_load / trimp)
    return {sport: median(ratios) for sport, ratios in grouped.items()
            if len(ratios) >= MIN_SPORT_SCALE_SESSIONS}


def scaled_session_load(sport: str, trimp: float | None, rpe: int | None,
                        duration_min: float | None, calibration: Calibration,
                        multipliers: Mapping[str, float]) -> tuple[float | None, str]:
    """Keep a whole sport on TRIMP until its rated HR reference is reliable."""
    if sport not in TEAM_SPORTS:
        return trimp, "trimp" if trimp is not None else "missing_hr"
    if calibration.factor is None:
        return trimp, "trimp_uncalibrated" if trimp is not None else "missing_hr"
    factor = multipliers.get(sport)
    if factor is None:
        return trimp, "trimp_unscaled_insufficient_ratings" if trimp is not None else "missing_hr"
    if rpe is None:
        return (trimp * factor if trimp is not None else None,
                "trimp_scaled_sport_median" if trimp is not None else "missing_hr")
    return combined_load(sport, trimp, rpe, duration_min, calibration)
