"""Pure Today presentation choices; training and recovery rules live elsewhere."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from coach.planning import is_hard
from web.formatting import sleep_hours

TODAY_FOLLOW_UPS = (
    "I only have 30 minutes today",
    "Can I do it later today?",
    "What if my legs feel heavy?",
)


def display_duration(minutes: int | float | None) -> str | None:
    return f"{round(minutes)} min" if minutes is not None else None


def session_name(sport: str, intent: str | None) -> str:
    intent = (intent or "").replace("_", " ").strip().lower()
    if sport == "running":
        return f"{intent} run" if intent else "run"
    if sport == "gym":
        if intent.startswith("light"):
            return "light gym"
        return f"{intent} gym" if intent and intent not in ("training", "strength") else "gym"
    if sport in ("football", "volleyball"):
        return f"{sport} {intent}" if intent and intent != "training" else sport
    return f"{intent} {sport}".strip()


def call_headline(intensity: str, workout: dict[str, Any] | None) -> str:
    if intensity == "rest":
        return "Rest day"
    if workout:
        return f"{intensity.title()} day — {workout['title'].lower()}"
    return f"{intensity.title()} day"


def dial_status(kind: str, value: float | None, usual: float | None) -> tuple[str, str]:
    if value is None:
        return "No data", "help"
    if kind == "recovery":
        return ("Good", "check") if value >= 70 else (("Low", "down") if value < 50 else ("Fair", "minus"))
    if usual is None or usual <= 0:
        return "No baseline", "help"
    relative = value / usual
    if kind == "sleep":
        return ("Above usual", "up") if relative > 1.05 else (
            ("Below usual", "down") if relative < 0.95 else ("Normal", "minus"))
    return ("Above usual", "up") if relative > 1.3 else (
        ("Below usual", "down") if relative < 0.8 else ("Normal", "minus"))


def dial_models(readiness: float | None, sleep: float | None, sleep_baseline: float | None,
                acute: float | None, chronic: float | None, sync: str) -> tuple[dict[str, Any], ...]:
    load_percent = acute / chronic * 100 if acute is not None and chronic and chronic > 0 else None
    values = (
        ("Recovery", "recovery", readiness, None, f"{readiness:.0f}" if readiness is not None else None, None),
        ("Sleep", "sleep", sleep, sleep_baseline, sleep_hours(sleep) if sleep is not None else None,
         f"usual {sleep_hours(sleep_baseline)}" if sleep_baseline is not None else None),
        ("Load", "load", acute, chronic, f"{load_percent:.0f}%" if load_percent is not None else None, None),
    )
    result = []
    for label, kind, value, usual, display, comparison in values:
        status, icon = dial_status(kind, value, usual)
        if display is None:
            status, icon = "No data", "help"
        percent = min(100, max(0, round((value / usual if usual and kind != "recovery" else
                                       (value or 0) / 100) * 100))) if display else 0
        spoken_value = f"{display} of usual" if kind == "load" and display else display
        result.append({"label": label, "kind": kind, "value": display or "No data",
                       "spoken_value": spoken_value or "No data", "status": status, "icon": icon,
                       "usual": comparison if display else sync, "percent": percent})
    return tuple(result)


def purpose_line(workout: dict[str, Any] | None, dials: tuple[dict[str, Any], ...]) -> str:
    states = {item["kind"]: item["status"] for item in dials}
    recovery = {"Good": "You're recovered", "Fair": "Recovery is fair", "Low": "Recovery is low"}.get(
        states.get("recovery"), "Recovery data is missing")
    load = {"Above usual": "your load is above usual", "Below usual": "your load is below usual",
            "Normal": "your load is normal"}.get(states.get("load"))
    sentence = f"{recovery} and {load}." if load else f"{recovery}."
    purpose = (workout or {}).get("purpose")
    return f"{purpose.rstrip('.').strip()}. {sentence}" if purpose else sentence


def display_decision_text(text: str) -> str:
    """Change only web wording and units; leave the stored explanation intact."""
    result = re.sub(r"\b(?:your )?readiness(?:\s+(?:is|of)|\s*:)?\s+(\d+(?:\.\d+)?)/100\b",
                    lambda match: f"{'Recovery' if match.group(0)[0].isupper() else 'recovery'} is {match.group(1)}", text,
                    flags=re.IGNORECASE)
    result = re.sub(r"\breadiness\b", lambda match: "Recovery" if match.group(0)[0].isupper()
                    else "recovery", result, flags=re.IGNORECASE)

    def ratio(match: re.Match[str]) -> str:
        return f"load is {float(match.group(1)) * 100:.0f}% of usual"

    result = re.sub(r"\b(?:your )?load ratio(?:\s+(?:is|of)|\s*:)?\s+(\d+(?:\.\d+)?)\b", ratio, result,
                    flags=re.IGNORECASE)
    result = re.sub(r"\bratio\s+(\d+(?:\.\d+)?)\b", ratio, result, flags=re.IGNORECASE)
    result = re.sub(r"\bload ratio\b", "load", result, flags=re.IGNORECASE)
    return result[:1].upper() + result[1:] if text[:1].isupper() else result


def format_chip(fact: dict[str, str]) -> dict[str, str] | None:
    value = fact.get("display", "")
    if not value or value == "No data":
        return None
    fact_id = fact["id"]
    if fact_id == "READINESS":
        return {"label": "Recovery", "value": value.replace("/100", ""), "source": fact["source"]}
    if fact_id == "LOAD_RATIO":
        try:
            value = f"{float(value) * 100:.0f}% of usual"
        except ValueError:
            return None
        return {"label": "Load", "value": value, "source": fact["source"]}
    if fact_id == "HARD_LAST_48H":
        if value.startswith(("no hard session in last 48 hours", "no hard session in the last 48 hours")):
            value = "none in the last 48 hours"
        return {"label": "Last hard session:", "value": value, "source": fact["source"]}
    if fact_id == "RHR_DELTA":
        return {"label": "Resting HR", "value": value, "source": fact["source"]}
    if fact_id == "HRV_DELTA":
        return {"label": "HRV", "value": value, "source": fact["source"]}
    label = fact["metric"].strip()
    if value.casefold().startswith(label.casefold()):
        value = value[len(label):].lstrip(" :")
    return {"label": label, "value": value, "source": fact["source"]}


def coach_evidence(decision: Any, limit: int = 4) -> tuple[dict[str, str], ...]:
    facts = {fact["id"]: fact for fact in decision.facts}
    ids = decision.evidence_ids or decision.rule_fact_ids
    selected = [format_chip(facts[item]) for item in ids if item in facts]
    return tuple(item for item in selected if item is not None)[:limit]


def workout_model(decision: Any, sessions: list[dict[str, Any]]) -> dict[str, Any] | None:
    planned = next((item for item in sessions if item["date"] == decision.date and
                    item.get("status") == "planned" and item.get("sport") != "mobility"), None)
    if decision.intensity == "rest":
        return None
    ranked = decision.sports[0] if decision.sports else None
    if planned:
        structure = planned.get("structure")
        return {"title": session_name(planned["sport"], planned.get("intent")),
                "intent": planned.get("intent"),
                "planned": True, "duration_min": planned.get("duration_min"),
                "duration": display_duration(planned.get("duration_min")),
                "structure": structure, "steps": tuple(part.strip() for part in structure.split(",") if part.strip())
                if structure else (), "sport": planned["sport"], "purpose": planned.get("purpose")}
    if not ranked:
        return None
    session = ranked["session"]
    return {"title": session_name(ranked["sport"], session.get("intent")),
            "intent": session.get("intent"),
            "planned": False, "duration_min": session.get("duration_min"),
            "duration": display_duration(session["duration_min"]), "structure": session.get("structure") or "",
            "steps": (), "sport": ranked["sport"], "purpose": None}


def week_day(current: date, today: date, planned: list[dict[str, Any]], logged: list[dict[str, Any]],
             unrated_id: int | None = None, recommendation: dict[str, Any] | None = None
             ) -> dict[str, Any]:
    """One source for Today strip and Training day contents."""
    planned = [item for item in planned if item.get("status") != "skipped"]
    key = current.isoformat()
    entries = []
    logged_ids = {item["id"] for item in logged}
    for actual in logged:
        entries.append({"title": session_name(actual["sport"], actual.get("intent")).capitalize(),
                        "done": True, "activity_id": actual["id"], "duration": actual.get("duration"),
                        "rate_id": actual.get("rate_id") or (actual["id"] if actual["id"] == unrated_id else None),
                        "badges": ("Done",)})
    for item in planned:
        if item["sport"] == "rest" or item.get("linked_activity_id") in logged_ids or item.get("status") == "done":
            continue
        origin = item.get("origin")
        badges = tuple(value for value in (
            "Fixed" if origin == "fixed" else "Habit" if origin == "protected" else None,
            "Hard" if is_hard(item) else None) if value)
        entries.append({"title": session_name(item["sport"], item.get("intent")).capitalize(),
                        "done": False, "origin": origin, "duration": display_duration(item.get("duration_min")),
                        "hr_cap": item.get("hr_cap_bpm"), "badges": badges,
                        "activity_id": None, "session": item})
    if current == today and recommendation and not planned:
        entries.append({"title": recommendation["title"].capitalize(), "done": False,
                        "duration": recommendation.get("duration"), "recommended": True,
                        "intent": recommendation.get("intent"), "sport": recommendation.get("sport"),
                        "badges": ("Suggested",), "activity_id": None})
    rest = any(item["sport"] == "rest" for item in planned)
    state = "done" if logged else "rest" if rest else "planned" if entries else "empty"
    if current == today:
        state = "done today" if state == "done" else "today"
    phone_next = next((entry["title"] for entry in entries if not entry["done"]), None)
    phone_done = next((entry["title"] for entry in entries if entry["done"]), None)
    return {"date": key, "weekday": current.strftime("%a"), "number": current.day,
            "day_label": f"{current:%a} {current.day}", "state": state,
            "icon": "check" if logged else "minus" if state in ("rest", "empty") else "circle",
            "entries": tuple(entries),
            "title": entries[0]["title"] if entries else "Rest day" if rest else "Nothing planned",
            "phone_title": ((phone_next.split()[0] if current == today else phone_next) if phone_next else
                            "Rest" if rest else "—" if not phone_done else phone_done),
            "phone_done": phone_done if phone_next else None}


def week_strip(day: date, sessions: list[dict[str, Any]], activities: list[dict[str, Any]],
               unrated_id: int | None = None, recommendation: dict[str, Any] | None = None
               ) -> tuple[dict[str, Any], ...]:
    start = day - timedelta(days=day.weekday())
    result = []
    for offset in range(7):
        current = start + timedelta(days=offset)
        key = current.isoformat()
        planned = [item for item in sessions if item["date"] == key]
        logged = [item for item in activities if item["date"] == key]
        result.append(week_day(current, day, planned, logged, unrated_id, recommendation))
    return tuple(result)
