"""Deterministic, display-ready facts and session rules for activity opinions."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TypedDict

from metrics.readiness import LOWER_LOAD, UPPER_LOAD
from services.fact_display import (
    as_number as _number,
)
from services.fact_display import (
    duration as _duration,
)
from services.fact_display import (
    heart_rate as _hr,
)
from services.fact_display import (
    hours as _hours,
)
from services.fact_display import (
    milliseconds as _ms,
)
from services.fact_display import (
    pace as _pace,
)
from services.fact_display import (
    percent as _percent,
)
from services.fact_display import (
    ratio as _ratio,
)
from services.fact_display import (
    score as _score,
)
from services.hr_zones import heart_rate_zone_bounds


class Fact(TypedDict):
    id: str
    metric: str
    display: str
    source: str


@dataclass(frozen=True)
class IntentDecision:
    intent: str
    fact_ids: tuple[str, ...]


RECOVERY_LOW_ZONE_MIN = 90.0
RECOVERY_Z2_FRACTION = 0.5
EASY_LOW_ZONE_MIN = 80.0
STEADY_Z3_PLUS_MIN = 20.0
STEADY_Z3_PLUS_MAX = 60.0
TEMPO_Z3_Z4_MIN = 60.0
RACE_Z4_PLUS_MIN = 50.0
FULL_KM_MIN = 0.9
FULL_KM_MAX = 1.1
PARTIAL_LAP_MAX_METRES = 100.0
PARTIAL_LAP_MIN_METRES = 1.0
CADENCE_STREAM_MAX = 110.0
CADENCE_LAP_MIN = 140.0
GPS_TIME_GAP_SECONDS = 30.0
GPS_DISTANCE_JUMP_KM = 0.2
EFFORT_HIGH_RPE = 7
EFFORT_LOW_RPE = 3
EFFORT_LOW_ZONE_SHARE = 80.0
EFFORT_HIGH_ZONE_SHARE = 50.0


def effort_vs_hr(rpe: int | None, z1_z2_percent: float | None) -> str | None:
    if rpe is None or z1_z2_percent is None:
        return None
    if rpe >= EFFORT_HIGH_RPE and z1_z2_percent >= EFFORT_LOW_ZONE_SHARE:
        return "higher than HR suggests"
    if rpe <= EFFORT_LOW_RPE and z1_z2_percent <= EFFORT_HIGH_ZONE_SHARE:
        return "lower than HR suggests"
    return "matches"


def _pace_seconds(value: Any) -> int | None:
    display = _pace(value)
    if display is None:
        return None
    minutes, seconds = display.split(" /km")[0].split(":")
    return int(minutes) * 60 + int(seconds)


def _add(facts: list[Fact], fact_id: str, metric: str, display: str | None, source: str) -> None:
    if display is not None:
        facts.append({"id": fact_id, "metric": metric, "display": display, "source": source})


def _full_km_laps(laps: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    return [(index, lap) for index, lap in enumerate(laps)
            if (distance := _number(lap.get("distance"))) is not None
            and FULL_KM_MIN <= distance <= FULL_KM_MAX]


def _partial_lap_metres(laps: list[dict[str, Any]], total_km: float | None) -> tuple[int, float] | None:
    completed_km = 0.0
    for index, lap in enumerate(laps):
        distance = _number(lap.get("distance"))
        if distance is None or distance <= 0:
            continue
        if distance < PARTIAL_LAP_MAX_METRES / 1000:
            if distance * 1000 >= PARTIAL_LAP_MIN_METRES:
                return index, distance * 1000
            continue
        duration = _number(lap.get("duration"))
        if (total_km is not None and completed_km >= total_km - 0.1
                and distance < PARTIAL_LAP_MAX_METRES and duration is not None and duration < 1):
            if distance >= PARTIAL_LAP_MIN_METRES:
                return index, distance
            continue
        if FULL_KM_MIN <= distance <= FULL_KM_MAX:
            completed_km += distance
    return None


def _cadence_multiplier(stream_mean: Any, laps: list[dict[str, Any]]) -> int:
    mean = _number(stream_mean)
    lap_values = [_number(lap.get("avg_cadence")) for lap in laps]
    valid_laps = [value for value in lap_values if value is not None and value > 0]
    return 2 if (mean is not None and 0 < mean < CADENCE_STREAM_MAX
                 and valid_laps and min(valid_laps) > CADENCE_LAP_MIN) else 1


def build_facts(activity_id: int, context: Mapping[str, Any]) -> list[Fact]:
    """Build a read-only facts pack from already-loaded activity context."""
    selected = context.get("selected_activity") or {}
    if selected.get("id") is not None and selected["id"] != activity_id:
        raise ValueError("Activity context does not match activity_id")
    facts: list[Fact] = []
    _add(facts, "ACTIVITY_DATE", "Activity date", str(selected.get("date")) if selected.get("date") else None,
         "selected_activity.date")
    distance = _number(selected.get("distance_km"))
    _add(facts, "DISTANCE", "Distance", f"{distance:.1f} km" if distance is not None else None,
         "selected_activity.distance_km")
    _add(facts, "DURATION", "Duration", _duration(selected.get("duration_min")), "selected_activity.duration_min")
    duration_minutes = _number(selected.get("duration_min"))
    if duration_minutes is not None and duration_minutes >= 5:
        suggested_minutes = max(5, 5 * round(duration_minutes / 5))
        _add(facts, "PLAN_DURATION_MIN", "Available plan duration", f"{suggested_minutes} min",
             "selected_activity.duration_min (rounded to 5 min)")
    _add(facts, "AVG_HR", "Average heart rate", _hr(selected.get("avg_hr")), "selected_activity.avg_hr")
    _add(facts, "MAX_HR", "Maximum heart rate", _hr(selected.get("max_hr")), "selected_activity.max_hr")
    _add(facts, "AVG_PACE", "Average pace", _pace(selected.get("pace")), "selected_activity.pace")
    effort = context.get("effort_rpe")
    zones = ((context.get("metrics_snapshot") or {}).get("zones") or {})
    low_share = context.get("effort_low_zone_share")
    if low_share is None and isinstance(zones, dict):
        low_share = sum(float(zones.get(zone, 0) or 0) for zone in ("Z1", "Z2")) or None
    if effort is not None:
        _add(facts, "EFFORT_RPE", "Session effort", f"{int(effort)}/10", "activity_efforts.rpe")
        mismatch = effort_vs_hr(int(effort), _number(low_share))
        _add(facts, "EFFORT_VS_HR", "Effort versus HR",
             f"rated {int(effort)}/10 while {_percent(low_share)} in Z1–Z2: {mismatch}"
             if mismatch and _percent(low_share) else None,
             "activity_efforts.rpe + metrics_snapshot.sessions.zones")
    for key, fact_id, metric in (("aerobic_effect", "AEROBIC_EFFECT", "Aerobic training effect"),
                                 ("anaerobic_effect", "ANAEROBIC_EFFECT", "Anaerobic training effect")):
        value = _number(selected.get(key))
        _add(facts, fact_id, metric, f"{value:.1f}" if value is not None else None, f"selected_activity.{key}")

    _add(facts, "RECENT_MEDIAN_PACE", "Recent median pace", _pace(context.get("recent_median_pace")),
         "recent_median_pace")
    goal_name = (context.get("active_goal") or {}).get("name")
    _add(facts, "GOAL", "Long-term goal", str(goal_name) if goal_name else None, "active_goal.name")
    planned = context.get("planned_intent")
    _add(facts, "PLAN_INTENT", "Planned intent", str(planned) if planned else None, "planned_intent")

    stream = context.get("stream_analysis") or {}
    laps = list((context.get("lap_analysis") or {}).get("laps") or [])
    cadence = stream.get("cadence_spm") or {}
    cadence_multiplier = _cadence_multiplier(cadence.get("avg"), laps)
    for key in ("avg", "min", "max"):
        value = _number(cadence.get(key))
        _add(facts, f"STREAM_CADENCE_{key.upper()}", f"Stream cadence {key}",
             f"{round(value * cadence_multiplier)} spm" if value is not None and value > 0 else None,
             f"stream_analysis.cadence_spm.{key}" + (" (doubled per-foot scale)" if cadence_multiplier == 2 else ""))
    for half, label in (("first_half", "FIRST_HALF"), ("second_half", "SECOND_HALF")):
        data = stream.get(half) or {}
        _add(facts, f"{label}_PACE", f"{half.replace('_', ' ').title()} pace", _pace(data.get("avg_pace")),
             f"stream_analysis.{half}.avg_pace")
        _add(facts, f"{label}_HR", f"{half.replace('_', ' ').title()} heart rate", _hr(data.get("avg_hr")),
             f"stream_analysis.{half}.avg_hr")
        half_cadence = _number(data.get("avg_cadence"))
        _add(facts, f"{label}_CADENCE", f"{half.replace('_', ' ').title()} cadence",
             f"{round(half_cadence * cadence_multiplier)} spm"
             if half_cadence is not None and half_cadence > 0 else None,
             f"stream_analysis.{half}.avg_cadence" + (" (doubled per-foot scale)" if cadence_multiplier == 2 else ""))
    first = _pace((stream.get("first_half") or {}).get("avg_pace"))
    second = _pace((stream.get("second_half") or {}).get("avg_pace"))
    if first and second:
        first_seconds = int(first.split(":")[0]) * 60 + int(first.split(":")[1].split()[0])
        second_seconds = int(second.split(":")[0]) * 60 + int(second.split(":")[1].split()[0])
        pattern = "negative split" if second_seconds < first_seconds else "positive split" if second_seconds > first_seconds else "even split"
        _add(facts, "SPLIT_PATTERN", "Pacing split", pattern,
             "stream_analysis.first_half.avg_pace + stream_analysis.second_half.avg_pace")

    full = _full_km_laps(laps)
    for km, (index, lap) in enumerate(full, start=1):
        _add(facts, f"KM{km}_PACE", f"Km {km} pace", _pace(lap.get("pace")), f"lap_analysis.laps[{index}].pace")
        _add(facts, f"KM{km}_AVG_HR", f"Km {km} average heart rate", _hr(lap.get("avg_hr")),
             f"lap_analysis.laps[{index}].avg_hr")
    if full:
        first_index, first_lap = full[0]
        last_index, last_lap = full[-1]
        _add(facts, "FIRST_FULL_KM", "First full kilometre", "km 1", f"lap_analysis.laps[{first_index}]")
        _add(facts, "FIRST_FULL_KM_PACE", "First full kilometre pace", _pace(first_lap.get("pace")),
             f"lap_analysis.laps[{first_index}].pace")
        _add(facts, "FIRST_FULL_KM_HR", "First full kilometre heart rate", _hr(first_lap.get("avg_hr")),
             f"lap_analysis.laps[{first_index}].avg_hr")
        _add(facts, "LAST_FULL_KM", "Last full kilometre", f"km {len(full)}", f"lap_analysis.laps[{last_index}]")
        _add(facts, "LAST_FULL_KM_PACE", "Last full kilometre pace", _pace(last_lap.get("pace")),
             f"lap_analysis.laps[{last_index}].pace")
        _add(facts, "LAST_FULL_KM_HR", "Last full kilometre heart rate", _hr(last_lap.get("avg_hr")),
             f"lap_analysis.laps[{last_index}].avg_hr")
        first_pace = _pace_seconds(first_lap.get("pace"))
        average_pace = _pace_seconds(selected.get("pace"))
        first_hr = _number(first_lap.get("avg_hr"))
        average_hr = _number(selected.get("avg_hr"))
        if (first_pace is not None and average_pace is not None and first_hr is not None
                and average_hr is not None and first_pace > average_pace and first_hr < average_hr):
            _add(facts, "CONSERVATIVE_START", "Conservative first kilometre", "yes",
                 f"lap_analysis.laps[{first_index}].pace + avg_hr vs selected_activity.pace + avg_hr")
        cadences = [_number(lap.get("avg_cadence")) for _, lap in full]
        cadence_values = [value for value in cadences if value is not None]
        if cadence_values:
            _add(facts, "LAP_CADENCE_RANGE", "Full-km lap cadence range",
                 f"{round(min(cadence_values))}–{round(max(cadence_values))} spm",
                 "lap_analysis.laps[*].avg_cadence")
    partial = _partial_lap_metres(laps, distance)
    if partial:
        _add(facts, "PARTIAL_LAP_DISTANCE", "Short partial lap", f"{partial[1]:.2f} m",
             f"lap_analysis.laps[{partial[0]}].distance")

    snapshot = context.get("metrics_snapshot") or {}
    session = snapshot.get("activity_session") or {}
    zones: dict[str, float] = {}
    for index, zone in enumerate(session.get("hr_zones") or []):
        match = re.match(r"Z([1-5])\b", str(zone.get("zone") or ""))
        value = _number(zone.get("percent"))
        if match and value is not None:
            name = f"Z{match.group(1)}"
            zones[name] = value
            _add(facts, f"ZONE_{name}", f"{name} time", _percent(value),
                 f"metrics_snapshot.activity_session.hr_zones[{index}].percent")
    for fact_id, metric, names in (("Z1_Z2_SHARE", "Z1–Z2 time", ("Z1", "Z2")),
                                   ("Z3_PLUS_SHARE", "Z3+ time", ("Z3", "Z4", "Z5")),
                                   ("Z3_Z4_SHARE", "Z3–Z4 time", ("Z3", "Z4")),
                                   ("Z4_PLUS_SHARE", "Z4+ time", ("Z4", "Z5"))):
        if all(name in zones for name in names):
            _add(facts, fact_id, metric, _percent(sum(zones[name] for name in names)),
                 "metrics_snapshot.activity_session.hr_zones.percent")
    hrmax = _number((session.get("hrmax") or {}).get("value"))
    if hrmax is not None and hrmax > 0:
        bounds = heart_rate_zone_bounds(round(hrmax))
        for zone_name, lower, upper in bounds:
            zone_id = zone_name.split()[0]
            _add(facts, f"ZONE_{zone_id}_LOWER_BPM", f"{zone_id} lower heart rate", _hr(math.ceil(lower)),
                 "services.hr_zones.heart_rate_zone_bounds + metrics_snapshot.activity_session.hrmax.value")
            upper_display = "no upper bpm limit" if math.isinf(upper) else _hr(math.ceil(upper) - 1)
            _add(facts, f"ZONE_{zone_id}_UPPER_BPM", f"{zone_id} upper heart rate", upper_display,
                 "services.hr_zones.heart_rate_zone_bounds + metrics_snapshot.activity_session.hrmax.value")
        z2 = bounds[1]
        _add(facts, "Z2_LOWER_HALF_CAP", "Z2 lower-half ceiling",
             _hr(z2[1] + RECOVERY_Z2_FRACTION * (z2[2] - z2[1])),
             "services.hr_zones.heart_rate_zone_bounds + metrics_snapshot.activity_session.hrmax.value")
        _add(facts, "Z3_UPPER_BPM", "Z3 upper boundary", _hr(bounds[2][2]),
             "services.hr_zones.heart_rate_zone_bounds + metrics_snapshot.activity_session.hrmax.value")

    readiness_field = (snapshot.get("readiness") or {}).get("score")
    readiness = _number(readiness_field.get("value") if isinstance(readiness_field, dict) else readiness_field)
    _add(facts, "READINESS", "Readiness", _score(readiness),
         "metrics_snapshot.readiness.score.value")
    for component in (snapshot.get("readiness") or {}).get("components") or []:
        name = component.get("name")
        score = _number((component.get("score") or {}).get("value"))
        if name in {"hrv", "rhr", "sleep", "load"} and score is not None:
            _add(facts, f"READINESS_{name.upper()}_SCORE", f"Readiness {name.upper()} component",
                 _score(score, decimals=1), f"metrics_snapshot.readiness.components.{name}.score.value")
    health = snapshot.get("current_health") or {}
    baselines = {(row.get("field"), row.get("days")): (row.get("mean") or {}).get("value")
                 for row in snapshot.get("baselines") or []}
    for key, prefix, days, formatter in (("hrv", "HRV", 28, _ms),
                                         ("resting_hr", "RHR", 7, _hr),
                                         ("sleep_duration", "SLEEP", 28, _hours)):
        current = (health.get(key) or {}).get("value")
        baseline = baselines.get((key, days))
        _add(facts, f"{prefix}_CURRENT", f"Current {prefix}", formatter(current),
             f"metrics_snapshot.current_health.{key}.value")
        _add(facts, f"{prefix}_BASELINE", f"{days}-day {prefix} baseline", formatter(baseline),
             f"metrics_snapshot.baselines.{key}.{days}.mean.value")
        current_value, baseline_value = _number(current), _number(baseline)
        if current_value is not None and baseline_value is not None:
            if key == "hrv" and baseline_value > 0:
                change = _percent((current_value / baseline_value - 1) * 100, signed=True)
            elif key == "resting_hr":
                change = f"{round(current_value - baseline_value):+d} bpm"
            elif key == "sleep_duration":
                change = f"{'+' if current_value >= baseline_value else '-'}{_hours(abs(current_value - baseline_value))}"
            else:
                change = None
            _add(facts, f"{prefix}_VS_BASELINE", f"{prefix} versus baseline", change,
                 f"metrics_snapshot.current_health.{key}.value vs metrics_snapshot.baselines.{key}.{days}.mean.value")
    ratio = _number(((snapshot.get("load") or {}).get("ratio") or {}).get("value"))
    _add(facts, "LOAD_RATIO", "Acute:chronic load ratio", _ratio(ratio),
         "metrics_snapshot.load.ratio.value")
    if ratio is not None:
        status = "below" if ratio < LOWER_LOAD else "above" if ratio > UPPER_LOAD else "in"
        _add(facts, "LOAD_RATIO_STATUS", "Load ratio status",
             f"{status} safe range {LOWER_LOAD:.1f}–{UPPER_LOAD:.1f}",
             "metrics_snapshot.load.ratio.value + metrics.readiness.LOWER_LOAD/UPPER_LOAD")
    return facts


def detect_intent(facts: list[Fact], planned_intent: str | None) -> IntentDecision | None:
    """Classify a session from displayed HR-zone shares and cite deciding facts."""
    values = {fact["id"]: fact["display"] for fact in facts}

    def numeric(fact_id: str) -> float | None:
        value = values.get(fact_id)
        return _number(re.match(r"[-+]?\d+(?:\.\d+)?", value).group() if value and re.match(r"[-+]?\d+(?:\.\d+)?", value) else None)

    if planned_intent == "race" and "PLAN_INTENT" in values:
        return IntentDecision("race", ("PLAN_INTENT",))
    z4_plus = numeric("Z4_PLUS_SHARE")
    if z4_plus is not None and z4_plus >= RACE_Z4_PLUS_MIN:
        return IntentDecision("race", ("Z4_PLUS_SHARE",))
    low = numeric("Z1_Z2_SHARE")
    avg_hr = numeric("AVG_HR")
    z2_cap = numeric("Z2_LOWER_HALF_CAP")
    if low is not None and low >= RECOVERY_LOW_ZONE_MIN and avg_hr is not None and z2_cap is not None and avg_hr <= z2_cap:
        return IntentDecision("recovery", ("Z1_Z2_SHARE", "AVG_HR", "Z2_LOWER_HALF_CAP"))
    z3_upper = numeric("Z3_UPPER_BPM")
    km_hrs = [(fact_id, numeric(fact_id)) for fact_id in values if re.fullmatch(r"KM\d+_AVG_HR", fact_id)]
    if low is not None and low >= EASY_LOW_ZONE_MIN and z3_upper is not None and all(
        hr is not None and hr < z3_upper for _, hr in km_hrs
    ):
        return IntentDecision("easy", ("Z1_Z2_SHARE", "Z3_UPPER_BPM", *(fact_id for fact_id, _ in km_hrs)))
    z3_z4 = numeric("Z3_Z4_SHARE")
    if z3_z4 is not None and z3_z4 >= TEMPO_Z3_Z4_MIN:
        return IntentDecision("tempo", ("Z3_Z4_SHARE",))
    z3_plus = numeric("Z3_PLUS_SHARE")
    if z3_plus is not None and STEADY_Z3_PLUS_MIN <= z3_plus <= STEADY_Z3_PLUS_MAX:
        return IntentDecision("steady", ("Z3_PLUS_SHARE",))
    return None


def build_data_notes(laps: list[dict[str, Any]], track_points: list[dict[str, Any]],
                     activity_distance_km: float | None) -> list[str]:
    """Report observed recording anomalies without guessing their cause."""
    notes: list[str] = []
    partial = _partial_lap_metres(laps, _number(activity_distance_km))
    if partial:
        notes.append(f"Partial lap: {partial[1]:.2f} m. Excluded from full-km analysis.")
    points = sorted(track_points, key=lambda row: row.get("point_index") or 0)
    for before, after in zip(points, points[1:], strict=False):
        t0, t1 = _number(before.get("elapsed_seconds")), _number(after.get("elapsed_seconds"))
        d0, d1 = _number(before.get("distance_km")), _number(after.get("distance_km"))
        if ((t0 is not None and t1 is not None and t1 - t0 > GPS_TIME_GAP_SECONDS)
                or (d0 is not None and d1 is not None and d1 - d0 > GPS_DISTANCE_JUMP_KM)):
            notes.append("GPS data gap observed between track points (time > 30 s or distance > 200 m).")
            break
    return notes


def match_text_facts(text: str, facts: list[Fact], preferred_ids: tuple[str, ...] = ()) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Match display values in text and return their IDs plus unsupported numbers."""
    compact = re.sub(r"\s+", "", text.casefold())
    preferred = set(preferred_ids)
    ordered = sorted(facts, key=lambda fact: (fact["id"] not in preferred, -len(fact["display"])))
    matched: list[str] = []
    for fact in ordered:
        display = re.sub(r"\s+", "", fact["display"].casefold())
        if display and re.search(r"\d", display) and display in compact:
            compact = compact.replace(display, " ")
            matched.append(fact["id"])
    compact = re.sub(r"z[1-5]\+?", " ", compact)
    return tuple(matched), tuple(sorted(set(re.findall(r"\d+(?:[:.]\d+)*", compact))))


def unsupported_text_numbers(text: str, facts: list[Fact]) -> tuple[str, ...]:
    """Return numeric claims not covered by a fact display after spacing normalization."""
    return match_text_facts(text, facts)[1]
