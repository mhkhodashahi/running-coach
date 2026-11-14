"""Pure weekly safety checks shared by drafting and approval."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from coach.load_model import LoadModel, estimate_load, is_recovery_item

MAX_HARD_DAYS = 2
MAX_QUALITY_RUNS = 1

def is_hard(session: dict[str, Any]) -> bool:
    return session["intent"] in ("tempo", "race") or (session["sport"] in ("football", "volleyball") and
           session["intent"] not in ("skills only", "recovery"))


def validate_week(sessions: list[dict[str, Any]], model: LoadModel, *, today: date,
                  decisions: dict[date, str], week_start: date | None = None) -> list[str]:
    """Return all rule failures; the model cannot waive these checks."""
    errors: list[str] = []
    hard_days = {date.fromisoformat(item["date"]) for item in sessions if is_hard(item) and
                 item.get("status", "planned") == "planned"}
    if len(hard_days) > MAX_HARD_DAYS:
        errors.append("More than two hard days")
    if sum(item["sport"] == "running" and item["intent"] in ("tempo", "race") and
           item.get("status", "planned") == "planned" for item in sessions) > MAX_QUALITY_RUNS:
        errors.append("More than one quality run")
    if any(day + timedelta(days=1) in hard_days for day in hard_days):
        errors.append("Hard days are consecutive")
    if any(day + timedelta(days=2) in hard_days for day in hard_days):
        errors.append("Hard days are too close for 48 h spacing without start times")
    if week_start is not None and not any(
            all(item["date"] != (week_start + timedelta(days=offset)).isoformat() or
                item.get("status", "planned") != "planned" or is_recovery_item(item) for item in sessions)
            for offset in range(7)):
        errors.append("No rest day in the week")
    total = 0.0
    protected_floor = 0.0
    for item in sessions:
        if item.get("status", "planned") != "planned":
            continue
        value = estimate_load(item, model)
        if value is None:
            errors.append(f"No own-session load median for {item['sport']}")
        else:
            total += value
            if item.get("origin") in ("fixed", "protected"):
                protected_floor += value
        day = date.fromisoformat(item["date"])
        if item.get("origin") not in ("fixed", "protected") and day in (today, today + timedelta(days=1)):
            intensity = decisions.get(day)
            if intensity == "rest" and item["intent"] not in ("skills only", "recovery"):
                errors.append(f"Session on {day} conflicts with rest decision")
            if intensity == "easy" and is_hard(item):
                errors.append(f"Hard session on {day} conflicts with easy decision")
    if model.cap is not None and total > max(model.cap, protected_floor) + 1e-8:
        errors.append("Projected weekly load exceeds 110% of the recent-week median")
    return errors


def apply_draft(existing: list[dict[str, Any]], changes: list[dict[str, Any]], *,
                allow_fixed_daily: bool = False) -> list[dict[str, Any]]:
    result = [dict(item) for item in existing]
    for change in changes:
        item = dict(change["session"])
        action = change["change_type"]
        if action not in ("add", "modify", "remove"):
            raise ValueError("Unknown change type")
        if action == "add":
            if any(row["date"] == item["date"] and row["sport"] == item["sport"] and
                   row.get("status", "planned") == "planned" for row in result):
                raise ValueError("Duplicate planned session")
            result.append({**item, "origin": "coach", "status": "planned"})
            continue
        target = next((row for row in result if row.get("id") == item.get("id") and row.get("id") is not None), None)
        if target is None:
            raise ValueError("Target planned session not found")
        if action == "modify" and item["date"] != target["date"]:
            raise ValueError("Moving a session requires remove and add changes")
        if target.get("origin") == "protected":
            raise ValueError("Protected habits are immutable in coach proposals")
        if target.get("origin") == "fixed" and (not allow_fixed_daily or action != "modify" or
                item["sport"] != target["sport"] or item["duration_min"] != target["duration_min"] or
                not (item["intent"] == "skills only" or item.get("status") == "skipped")):
            raise ValueError("Fixed commitments are immutable in weekly plans")
        if action == "remove":
            result.remove(target)
        else:
            target.update({key: item[key] for key in ("sport", "intent", "duration_min", "hr_cap_bpm", "notes", "status",
                                                       "workout_type", "workout")
                           if key in item})
    return result
