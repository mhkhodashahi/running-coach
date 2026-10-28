"""Pure sport-specific Activity presentation built from existing facts and opinions."""

from __future__ import annotations

from typing import Any


def list_row(title: str | None, sport: str, distance: str | None,
             load: float | None, sync: str) -> dict[str, str]:
    icon = "run" if sport == "running" else "gym" if sport == "gym" else "ball"
    detail = distance if sport == "running" else f"{round(load)} load" if load is not None else f"No data · {sync}"
    return {"title": title or sport.title(), "icon": icon, "detail": detail or f"No data · {sync}"}


def sport_numbers(stats: list[tuple[str, str | None]], sport: str, sync: str
                  ) -> tuple[tuple[dict[str, str], ...], tuple[str, ...]]:
    by_label = dict(stats)
    primary = ("Distance", "Time", "Avg pace", "Avg HR") if sport == "running" else (
        "Duration", "Avg HR", "Session load")
    numbers = tuple({"label": label.replace("Avg pace", "Pace").replace("Avg HR", "Avg heart rate"),
                     "value": by_label.get(label) or f"No data · {sync}"} for label in primary)
    secondary = tuple(f"{label} {value}" for label, value in stats if label not in primary and value is not None)
    return numbers, secondary


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
    duration = lookup.get("DURATION")
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


def build_activity_view(context: dict[str, Any], facts: list[dict[str, str]]) -> dict[str, Any]:
    activity = context["activity"]
    numbers, secondary = sport_numbers(context["stats"], activity["category"], context["sync"])
    return {"numbers": numbers, "secondary": secondary,
            "opinion_preview": opinion_preview(context["opinion"]),
            "tabs": activity_tabs(context["opinion"], context["laps"], context["similar"]),
            "coach_summary": coach_fact_summary(activity, facts, context["sync"]),
            "team_note": activity["category"] in ("volleyball", "football"),
            "fact_chips": tuple({"label": fact["metric"], "value": fact["display"]}
                                for fact in facts if fact["id"].endswith(("DISTANCE", "DURATION", "AVG_HR"))
                                and fact["display"] != "No data")[:3]}
