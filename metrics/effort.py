"""Perceived exertion load, calibrated against the athlete's HR history."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

MIN_CALIBRATION_SESSIONS = 5
DEFAULT_TRIMP_PER_SRPE = 0.5
TEAM_SPORTS = frozenset({"volleyball", "football", "gym"})


@dataclass(frozen=True)
class Calibration:
    factor: float
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
        return Calibration(DEFAULT_TRIMP_PER_SRPE, len(ratios), "documented_default")
    return Calibration(median(ratios), len(ratios), "median_hr_trimp_per_srpe")


def combined_load(sport: str, trimp: float | None, rpe: int | None,
                  duration_min: float | None, calibration: Calibration) -> tuple[float | None, str]:
    if sport not in TEAM_SPORTS or rpe is None or duration_min is None:
        return trimp, "trimp" if trimp is not None else "missing_hr"
    perceived = calibration.factor * srpe_load(rpe, duration_min)
    return (max(trimp, perceived) if trimp is not None else perceived,
            "max_trimp_calibrated_srpe" if trimp is not None else "calibrated_srpe_no_hr")
