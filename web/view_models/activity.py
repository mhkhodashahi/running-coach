"""Pure sport-specific Activity presentation built from existing facts and opinions."""

from __future__ import annotations

import json
import re
from typing import Any

from web.formatting import activity_duration, sleep_hours

LEGACY_SECTION_KEYS = {
    "pacing": "pacing_analysis", "aerobic": "aerobic_efficiency_analysis",
    "recovery": "recovery_analysis", "mental": "mental_performance_insights",
}


def _first_sentence(value: str, limit: int = 120) -> str:
    sentence = re.split(r"(?<=[.!?])\s+", value.strip(), maxsplit=1)[0]
    return sentence if len(sentence) <= limit else sentence[:limit - 1].rstrip() + "…"


def _legacy_rows(value: Any) -> tuple[tuple[str, str], ...]:
    if isinstance(value, dict):
        entries = value.items()
    elif isinstance(value, list):
        entries = (("", item) for item in value)
    else:
        return ()
    rows = []
    for key, item in entries:
        if item in (None, "", [], {}):
            continue
        if isinstance(item, dict):
            nested = _legacy_rows(item)
            if key:
                rows.extend(nested)
            else:
                rows.append(("", " · ".join(f"{label} {text}" for label, text in nested)))
            continue
        if isinstance(item, list):
            for nested in item:
                rows.extend(_legacy_rows([nested]))
            continue
        rows.append(_legacy_field(str(key), item))
    return tuple(rows)


def _legacy_field(key: str, value: Any) -> tuple[str, str]:
    normalized = key.lower()
    zone = re.match(r"(?:zone|z)[ _]?([1-5])(?:\b|_)", normalized)
    label = f"Z{zone.group(1)}" if zone else key.replace("_", " ").strip().capitalize()
    label = re.sub(r"\bhrv\b", "HRV", label, flags=re.I)
    label = re.sub(r"\bhr\b", "HR", label, flags=re.I)
    label = re.sub(r"\bvs\b", "vs", label, flags=re.I)
    if normalized.endswith("_bpm"):
        label = label.removesuffix(" bpm")
    text = str(value)
    numeric_text = text.removesuffix(" h").strip() if normalized == "sleep_duration" else text
    numeric = (float(numeric_text) if not isinstance(value, bool) and
               re.fullmatch(r"-?\d+(?:\.\d+)?", numeric_text) else None)
    if numeric is not None:
        if normalized == "sleep_duration":
            text = sleep_hours(numeric) or text
        elif normalized == "recovery_time":
            text = f"{numeric:g} h"
        elif zone or "percent" in normalized or normalized.endswith("_pct"):
            text = f"{round(numeric)}%" if zone else f"{numeric:g}%"
        elif normalized == "hrv" or normalized.endswith("_hrv"):
            text = f"{round(numeric)} ms"
        elif re.search(r"(?:^|_)(?:hr|rhr)(?:_|$)", normalized) or "heart_rate" in normalized:
            amount = f"{round(numeric)}" if normalized in ("avg_hr", "resting_hr", "max_hr", "rhr") else f"{numeric:g}"
            text = f"{amount} bpm"
        else:
            text = f"{numeric:g}"
    elif "pace" in normalized and re.fullmatch(r"\d+:\d{2}", text):
        text += " /km"
    elif normalized in ("first_half", "second_half") and re.fullmatch(r"\d+:\d{2}", text):
        text += " /km"
    return label, text


def display_opinion(opinion: dict[str, Any] | None, raw_payload: dict[str, Any] | None,
                    *, legacy: bool) -> dict[str, Any] | None:
    """Prepare a rendering copy; never mutate a stored opinion."""
    if opinion is None:
        return None
    result = {**opinion}
    result["section_rows"] = {}
    if legacy:
        full_headline = str(result.get("headline") or "").strip()
        original_conclusion = str((raw_payload or {}).get("brutally_honest_conclusion") or "").strip()
        original_headline = str((raw_payload or {}).get("headline") or original_conclusion or full_headline).strip()
        full_first_sentence = re.split(r"(?<=[.!?])\s+", original_headline, maxsplit=1)[0]
        headline = _first_sentence(full_headline)
        result["headline"] = headline
        conclusion = str(result.get("conclusion") or "").strip()
        if conclusion.startswith(headline):
            result["conclusion"] = conclusion[len(headline):].lstrip(" .")
        assessment = str(result.get("assessment") or "").strip()
        if assessment.startswith(full_first_sentence):
            result["assessment"] = assessment[len(full_first_sentence):].lstrip(" .")
        elif assessment.startswith(headline):
            result["assessment"] = assessment[len(headline):].lstrip(" .")
        for section, key in LEGACY_SECTION_KEYS.items():
            value = (raw_payload or {}).get(key)
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, (dict, list)):
                    value = parsed
            if isinstance(value, (dict, list)):
                result["section_rows"][section] = _legacy_rows(value)
                result["sections"] = {**result["sections"], section: ""}
    return result


def list_row(title: str | None, sport: str, distance: str | None,
             load: float | None, sync: str) -> dict[str, str]:
    icon = ("run" if sport == "running" else "gym" if sport == "gym" else
            "ball" if sport in ("football", "volleyball") else "activity")
    detail = distance if sport == "running" else f"{round(load)} load" if load is not None else f"No data · {sync}"
    return {"title": title or sport.title(), "icon": icon, "detail": detail or f"No data · {sync}"}


def sport_numbers(stats: list[tuple[str, str | None]], sport: str, sync: str
                  ) -> tuple[tuple[dict[str, str], ...], tuple[str, ...]]:
    by_label = dict(stats)
    primary = ("Distance", "Time", "Avg pace", "Avg HR") if sport == "running" else (
        "Duration", "Avg HR", "Session load")
    numbers = tuple({"label": label.replace("Avg pace", "Pace").replace("Avg HR", "Avg heart rate"),
                     "value": by_label.get(label) or f"No data · {sync}"} for label in primary)
    secondary = []
    aerobic, anaerobic = by_label.get("Aerobic TE"), by_label.get("Anaerobic TE")
    if aerobic or anaerobic:
        secondary.append("Training effect: " + " · ".join(
            f"{label} {value}" for label, value in (("aerobic", aerobic), ("anaerobic", anaerobic)) if value))
    secondary.extend(f"{label.replace('Session load', 'Load')} {value}" for label, value in stats
                     if label not in primary and label not in ("Aerobic TE", "Anaerobic TE") and value is not None)
    return numbers, tuple(secondary)


def opinion_preview(opinion: dict[str, Any] | None) -> dict[str, Any] | None:
    if not opinion:
        return None
    icons = {"good": "check", "watch": "minus", "poor": "close"}
    return {"headline": opinion["headline"],
            "verdicts": tuple({"aspect": item["aspect"], "word": item["word"],
                               "icon": icons[item["rating"]]} for item in opinion.get("verdicts", [])),
            "legacy": not opinion.get("verdicts")}


def activity_tabs(opinion: dict[str, Any] | None, laps: list[dict[str, Any]],
                  similar: list[dict[str, Any]]) -> tuple[dict[str, str], ...]:
    tabs = [{"id": "activity-overview", "label": "Overview"}]
    if opinion:
        tabs.append({"id": "activity-review", "label": "Coach review"})
    if laps:
        tabs.append({"id": "activity-laps", "label": "Laps"})
    if similar:
        tabs.append({"id": "activity-compare", "label": "Compare"})
    return tuple(tabs)


def coach_fact_summary(activity: dict[str, Any], facts: list[dict[str, str]], sync: str) -> str:
    activity_id = activity["id"]
    prefix = f"ACT_{activity_id}_"
    lookup = {fact["id"].removeprefix(prefix): fact["display"] for fact in facts}
    duration_fact = next((fact for fact in facts if fact["id"] == prefix + "DURATION"), None)
    duration = _chip_value(duration_fact) if duration_fact else None
    heart_rate = lookup.get("AVG_HR")
    if activity["category"] == "running":
        distance = lookup.get("DISTANCE")
        pace = lookup.get("AVG_PACE")
        if distance and pace:
            return f"You ran {distance} at {pace}. Average heart rate was {heart_rate or 'not recorded'}."
    if duration:
        return f"Your {activity['sport'].lower()} session lasted {duration}. Average heart rate was " + (
            f"{heart_rate}." if heart_rate else f"not recorded · {sync}.")
    return f"Session facts: No data · {sync}."


def _chip_value(fact: dict[str, str]) -> str:
    value = fact["display"]
    hour_time = re.fullmatch(r"(\d+):(\d{2}) h", value) if fact["id"].endswith("DURATION") else None
    if hour_time:
        return f"{int(hour_time.group(1))}h {int(hour_time.group(2)):02d}m"
    if fact["id"].endswith("DURATION") and re.fullmatch(r"\d+:\d{2}", value):
        minutes, seconds = map(int, value.split(":"))
        return activity_duration(minutes + seconds / 60) or value
    return value


def difference_words(pace: str | None, duration: str | None, hr: str | None) -> str | None:
    """Translate the comparison tool's signed display facts into athlete-facing words."""
    parts = []
    for value, unit, negative, positive, unchanged in (
        (pace, "s/km", "faster", "slower", "same pace"),
        (duration, "min", "shorter", "longer", "same duration"),
        (hr, "bpm", "lower", "higher", "same heart rate"),
    ):
        if not value:
            continue
        match = re.fullmatch(r"([+−-]?\d+)\s*" + re.escape(unit), value.strip())
        if not match:
            continue
        amount = int(match.group(1).replace("−", "-"))
        parts.append(f"{abs(amount)} {unit} {negative if amount < 0 else positive}" if amount else unchanged)
    return " · ".join(parts) if parts else None


def comparison_columns(similar: list[dict[str, Any]], sport: str) -> dict[str, bool | str]:
    duration_based = sport in ("gym", "football", "volleyball")
    return {"measure": "Duration" if duration_based else "Pace",
            "measure_visible": any(item.get("duration" if duration_based else "pace") for item in similar),
            "hr": any(item.get("hr") for item in similar),
            "load": duration_based and any(item.get("load") for item in similar),
            "difference": any(item.get("difference") for item in similar),
            "status": not duration_based and any(item.get("efficiency") for item in similar)}


def build_activity_view(context: dict[str, Any], facts: list[dict[str, str]]) -> dict[str, Any]:
    activity = context["activity"]
    numbers, secondary = sport_numbers(context["stats"], activity["category"], context["sync"])
    return {"numbers": numbers, "secondary": secondary,
            "opinion_preview": opinion_preview(context["opinion"]),
            "tabs": activity_tabs(context["opinion"], context["laps"], context["similar"]),
            "compare_columns": comparison_columns(context["similar"], activity["category"]),
            "coach_summary": coach_fact_summary(activity, facts, context["sync"]),
            "team_note": activity["category"] in ("volleyball", "football"),
            "fact_chips": tuple({"label": fact["metric"], "value": _chip_value(fact)}
                                for fact in facts if fact["id"].endswith(("DISTANCE", "DURATION", "AVG_HR"))
                                and fact["display"] != "No data" and
                                (not fact["id"].endswith("DISTANCE") or
                                 activity["category"] == "running" and fact["display"] != "0.0 km"))[:3]}
