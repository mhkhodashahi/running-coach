"""Readiness v1 constants and explainable, missing-aware components."""

from dataclasses import replace
from datetime import date, timedelta
from math import isclose, isfinite
from types import MappingProxyType

from metrics.models import Component, Metric, Readiness, metric

WEIGHTS = MappingProxyType({"hrv": 35.0, "sleep": 25.0, "rhr": 20.0, "load": 20.0})
MIDPOINT = 50.0
HRV_SCALE = 250.0
RHR_SCALE = 7.0
LOWER_LOAD = 0.8
UPPER_LOAD = 1.3
LOW_LOAD_FLOOR = 0.5
HIGH_LOAD_ZERO = 1.8
ILLNESS_RHR_DELTA = 7.0
ILLNESS_HRV_DROP = -0.15
MIN_COMPONENTS = 2


def clamp(value: float, as_of: date) -> float:
    return max(0.0, min(100.0, value))


def load_score(ratio: float | None, as_of: date) -> float | None:
    if ratio is None or not isfinite(ratio) or ratio < 0:
        return None
    if ratio < LOWER_LOAD:
        return MIDPOINT + MIDPOINT * max(0.0, ratio - LOW_LOAD_FLOOR) / (LOWER_LOAD - LOW_LOAD_FLOOR)
    if ratio <= UPPER_LOAD:
        return 100.0
    return clamp(100 * (HIGH_LOAD_ZERO - ratio) / (HIGH_LOAD_ZERO - UPPER_LOAD), as_of)


def readiness(current: dict[str, Metric], baselines: dict[tuple[str, int], Metric], ratio: Metric,
              sleep_goal_hours: float, as_of: date) -> Readiness:
    if not isfinite(sleep_goal_hours) or sleep_goal_hours <= 0:
        raise ValueError("sleep_goal_hours must be positive and finite")
    current = {key: item if item.provenance.window_end <= as_of.isoformat() else replace(item, value=None)
               for key, item in current.items()}
    baselines = {key: item if item.provenance.window_end < as_of.isoformat() else replace(item, value=None)
                 for key, item in baselines.items()}
    if ratio.provenance.window_end > as_of.isoformat():
        ratio = replace(ratio, value=None)
    hrv, rhr, sleep = (current[name].value for name in ("hrv", "resting_hr", "sleep_duration"))
    hrv_base, rhr_base = baselines["hrv", 28].value, baselines["resting_hr", 7].value
    hrv_change = hrv / hrv_base - 1 if hrv is not None and hrv_base is not None and hrv_base > 0 else None
    rhr_change = rhr - rhr_base if rhr is not None and rhr_base is not None else None
    scores = {
        "hrv": clamp(MIDPOINT + hrv_change * HRV_SCALE, as_of) if hrv_change is not None else None,
        "sleep": clamp(sleep / sleep_goal_hours * 100, as_of) if sleep is not None else None,
        "rhr": clamp(MIDPOINT - rhr_change * RHR_SCALE, as_of) if rhr_change is not None else None,
        "load": load_score(ratio.value, as_of),
    }
    evidence = {
        "hrv": baselines["hrv", 28].provenance,
        "rhr": baselines["resting_hr", 7].provenance,
        "sleep": current["sleep_duration"].provenance,
        "load": ratio.provenance,
    }
    total = sum(WEIGHTS[name] for name, score in scores.items() if score is not None)
    available = [name for name, score in scores.items() if score is not None]
    value = None
    if len(available) >= MIN_COMPONENTS and any(name in available for name in ("hrv", "rhr")):
        value = sum(scores[name] * WEIGHTS[name] for name in available) / total
    components = tuple(Component(name,
        metric(score, "score/100", (*evidence[name].sources, "config.sleep_goal_hours") if name == "sleep" else evidence[name].sources,
               date.fromisoformat(evidence[name].window_start), as_of, evidence[name].n_days, f"readiness_v1_{name}"),
        WEIGHTS[name] / total if score is not None else 0.0) for name, score in scores.items())
    illness = None
    if hrv_change is not None and rhr_change is not None:
        illness = (rhr_change >= ILLNESS_RHR_DELTA or isclose(rhr_change, ILLNESS_RHR_DELTA)) and (
            hrv_change <= ILLNESS_HRV_DROP or isclose(hrv_change, ILLNESS_HRV_DROP))
    start = as_of - timedelta(days=28)
    sources = tuple(dict.fromkeys(source for component in components for source in component.score.provenance.sources))
    n_days = max(p.n_days for p in evidence.values())
    return Readiness(metric(value, "score/100", sources, start, as_of, n_days, "readiness_v1_available_weight_normalization"),
                     components, metric(illness, "flag", ("health_metrics.resting_hr", "health_metrics.hrv", "health_metrics.date"),
                                        start, as_of, min(evidence["hrv"].n_days, evidence["rhr"].n_days),
                                        "rhr_delta_gte_7_and_hrv_relative_change_lte_minus_0.15; not_a_diagnosis"))
