"""Pure presentation shaping for the Training week and proposal review."""

from __future__ import annotations

from datetime import date, timedelta
from math import ceil
from typing import Any

from coach.planning import MAX_WEEKLY_INCREASE, estimate_load, is_hard
from web.formatting import short_date
from web.view_models.today import dial_status, display_duration, session_name, week_day

SAFE_LIMIT_PERCENT = round(MAX_WEEKLY_INCREASE * 100)
LOAD_BAR_MAX_PERCENT = 130


def training_follow_ups(status: str, proposal_open: bool) -> tuple[str, ...]:
    first = "Should I review the coach's suggestions?" if proposal_open else "Could I move a session this week?"
    if status == "Above usual":
        return (first, "How can I make this week easier?", "Which session should I keep?")
    if status == "Below usual":
        return (first, "Is there room for an easy run?", "Why is this week lighter?")
    return (first, "Is there room for an easy run?", "How does this week compare with usual?")


def percentage(value: float | None, usual: float | None) -> int | None:
    if value is None or usual is None or usual <= 0:
        return None
    return round(value / usual * 100)


def selected_groups(groups: list[dict[str, Any]], change_ids: list[int]) -> tuple[list[str], int]:
    selected = set(change_ids)
    known = {change["id"] for group in groups for change in group["changes"]}
    if selected - known:
        raise ValueError("Unknown proposal change")
    chosen = []
    for group in groups:
        ids = {change["id"] for change in group["changes"]}
        if selected & ids and not ids <= selected:
            raise ValueError("Linked changes must be selected together")
        if ids <= selected:
            chosen.append(group["id"])
    return chosen, len(selected)


def proposal_view(proposal: dict[str, Any], week: dict[str, Any], model: Any,
                  selected: list[int] | None = None) -> dict[str, Any]:
    groups = proposal["groups"]
    if selected is None:
        selected = [change["id"] for group in groups for change in group["changes"]]
    selected_group_ids, count = selected_groups(groups, selected)
    details = []
    existing = {session.get("id"): session for day in week["days"] for session in day["sessions"]}
    for group in groups:
        for change in group["changes"]:
            after = estimate_load(change["session"], model)
            before_session = existing.get(change["session"].get("id"))
            before = estimate_load(before_session, model) if before_session else None
            if change["change_type"] == "remove":
                load = -before if before is not None else None
            elif change["change_type"] == "modify":
                load = after - before if after is not None and before is not None else None
            else:
                load = after
            details.append({**change, "title": f"{short_date(change['session']['date'])} · "
                            f"{session_name(change['session']['sport'], change['session']['intent']).capitalize()} "
                            f"{display_duration(change['session']['duration_min'])}",
                            "delta": round(load) if load is not None else None,
                            "selected": change["id"] in selected})
    return {**proposal, "change_rows": details, "selected_group_ids": selected_group_ids,
            "selected_count": count, "now_percent": percentage(week["total"], week.get("usual")),
            "applied_percent": percentage(proposal.get("projected_total"), week.get("usual")),
            "stale": proposal["status"] == "stale"}


def week_view(week: dict[str, Any], today: date, sync: str,
              recommendation: dict[str, Any] | None = None) -> dict[str, Any]:
    start = date.fromisoformat(week["start"])
    days = []
    for day in week["days"]:
        current = date.fromisoformat(day["date"])
        shared = week_day(current, today, day["sessions"], day["actuals"], recommendation=recommendation)
        entries = [dict(entry, duration=entry.get("duration") or f"No data · {sync}")
                   if entry["done"] else entry for entry in shared["entries"]]
        days.append({**day, **shared, "today": current == today, "past": current < today, "entries": entries,
                     "empty": day["empty_label"], "estimated_load": day["estimated_load"]})
    done = sum(len(day["actuals"]) for day in week["days"])
    planned = sum(1 for day in week["days"] for session in day["sessions"]
                  if session.get("status") != "skipped" and session["sport"] not in ("rest", "mobility")
                  and not session.get("linked_activity_id"))
    planned_hard = sum(any(entry.get("session") and is_hard(entry["session"])
                           for entry in day["entries"] if not entry["done"]) for day in days)
    hard = sum(any((entry.get("session") and is_hard(entry["session"])) or
                   (entry.get("recommended") and is_hard(entry))
                   for entry in day["entries"] if not entry["done"]) for day in days)
    suggested_hard = next((entry["title"].lower() for day in days for entry in day["entries"]
                           if entry.get("recommended") and is_hard(entry)), None)
    suggested_title = next((entry["title"].lower() for day in days for entry in day["entries"]
                            if entry.get("recommended")), None)
    rest = sum(not day["entries"] and day["empty"] == "Rest day" for day in days)
    total_percent = percentage(week["total"], week.get("usual"))
    actual_percent = percentage(week["actual_total"], week.get("usual"))
    suggested_load = week.get("suggested_load")
    suggested_percent = (percentage(week["total"] + suggested_load, week.get("usual"))
                         if week["total"] is not None and suggested_load is not None else None)
    status, status_icon = dial_status("load", float(total_percent) if total_percent is not None else None, 100)
    return {**week, "days": days, "done_count": done, "session_count": done + planned,
            "actual_percent": actual_percent, "total_percent": total_percent,
            "planned_percent": max(0, total_percent - actual_percent)
            if total_percent is not None and actual_percent is not None else None,
            "hard_count": hard, "planned_hard_count": planned_hard, "rest_count": rest, "sync": sync,
            "load_status": status, "load_icon": status_icon,
            "bar_actual": min(100, round((actual_percent or 0) / LOAD_BAR_MAX_PERCENT * 100)),
            "bar_total": min(100, ceil((total_percent or 0) / LOAD_BAR_MAX_PERCENT * 100)),
            "safe_marker": round(SAFE_LIMIT_PERCENT / LOAD_BAR_MAX_PERCENT * 100),
            "suggested_hard_title": suggested_hard,
            "suggested_title": suggested_title,
            "with_suggested_percent": suggested_percent,
            "range_label": f"{short_date(start)} – {short_date(start + timedelta(days=6))}"}


def coach_summary(week: dict[str, Any]) -> tuple[str, tuple[dict[str, str], ...]]:
    hard = week["hard_count"]
    rest = week["rest_count"]
    percent = week["total_percent"]
    chips = []
    if hard:
        chips.append({"label": "Hard days", "value": str(hard)})
    if percent is not None:
        chips.append({"label": "Load", "value": f"{percent}% of usual"})
    if rest:
        chips.append({"label": "Rest days", "value": str(rest)})
    if percent is None:
        return f"Load: No data · {week['sync']}.", tuple(chips)
    summary = f"Your plan puts load at {percent}% of usual"
    if percent > SAFE_LIMIT_PERCENT:
        summary += f", above the {SAFE_LIMIT_PERCENT}% safe limit"
    elif percent == SAFE_LIMIT_PERCENT:
        summary += f", right at the {SAFE_LIMIT_PERCENT}% safe limit"
    else:
        summary += f", {week['load_status'].lower()}"
    summary += "."
    if week["suggested_hard_title"]:
        title = week["suggested_hard_title"]
        summary += (f" No hard session is planned; today's {title} is suggested." if not
                    week["planned_hard_count"] else f" Today's {title} is suggested as well as the plan.")
    elif hard:
        summary += f" {hard} hard {'day is' if hard == 1 else 'days are'} in the plan."
    if week["suggested_title"] and week["with_suggested_percent"] is not None:
        summary += f" With today's {week['suggested_title']}: {week['with_suggested_percent']}% of usual."
    if week.get("weekly_limit_reason") == "shortened to fit the weekly limit":
        summary += " Today's suggestion was shortened to fit the weekly limit."
    elif week.get("weekly_limit_reason") == "easy: no room in the weekly limit":
        summary += " There is no room for a hard session within the weekly limit."
    return summary, tuple(chips)
