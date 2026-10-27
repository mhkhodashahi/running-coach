"""Pure presentation shaping for the Training week and proposal review."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from coach.planning import MAX_WEEKLY_INCREASE, estimate_load, is_hard
from web.formatting import short_date
from web.view_models.today import display_duration, session_name

TRAINING_FOLLOW_UPS = (
    "Could I move a session this week?",
    "Is there room for an easy run?",
    "Why is this week lighter?",
)


def percentage(value: float | None, cap: float | None) -> int | None:
    if value is None or cap is None or cap <= 0:
        return None
    return round(value / (cap / MAX_WEEKLY_INCREASE) * 100)


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
            "selected_count": count, "now_percent": percentage(week["total"], week["cap"]),
            "applied_percent": percentage(proposal.get("projected_total"), week["cap"]),
            "stale": proposal["status"] == "stale"}


def week_view(week: dict[str, Any], today: date, sync: str) -> dict[str, Any]:
    start = date.fromisoformat(week["start"])
    sessions = [session for day in week["days"] for session in day["sessions"]]
    days = []
    for day in week["days"]:
        current = date.fromisoformat(day["date"])
        entries = []
        for activity in day["actuals"]:
            entries.append({"title": session_name(activity["sport"], None).capitalize(),
                            "duration": activity["duration"] or f"No data · {sync}",
                            "activity_id": activity["id"], "done": True,
                            "rate_id": activity.get("rate_id"), "badges": ("Done",)})
        for session in day["sessions"]:
            if session.get("status") == "skipped":
                continue
            if session.get("linked_activity_id") in {row["id"] for row in day["actuals"]}:
                continue
            origin = session.get("origin")
            badges = tuple(value for value in (
                "Fixed" if origin == "fixed" else "Habit" if origin == "protected" else None,
                "Hard" if is_hard(session) else None) if value)
            entries.append({"title": session_name(session["sport"], session.get("intent")).capitalize(),
                            "duration": display_duration(session.get("duration_min")),
                            "hr_cap": session.get("hr_cap_bpm"), "badges": badges,
                            "done": False, "activity_id": None, "session": session})
        days.append({**day, "weekday": current.strftime("%a"), "number": current.day,
                     "today": current == today, "past": current < today, "entries": entries,
                     "empty": day["empty_label"], "estimated_load": day["estimated_load"]})
    done = sum(len(day["actuals"]) for day in week["days"])
    planned = sum(1 for day in week["days"] for session in day["sessions"]
                  if session.get("status") != "skipped" and session["sport"] not in ("rest", "mobility")
                  and not session.get("linked_activity_id"))
    hard = sum(is_hard(session) for session in sessions if session.get("status") == "planned")
    rest = sum(not day["entries"] and day["empty"] == "Rest day" for day in days)
    total_percent = percentage(week["total"], week["cap"])
    actual_percent = percentage(week["actual_total"], week["cap"])
    return {**week, "days": days, "done_count": done, "session_count": done + planned,
            "actual_percent": actual_percent, "total_percent": total_percent,
            "planned_percent": max(0, total_percent - actual_percent)
            if total_percent is not None and actual_percent is not None else None,
            "hard_count": hard, "rest_count": rest, "sync": sync,
            "range_label": f"{short_date(start)} – {short_date(start + timedelta(days=6))}"}


def coach_summary(week: dict[str, Any]) -> tuple[str, tuple[dict[str, str], ...]]:
    hard = week["hard_count"]
    rest = week["rest_count"]
    percent = week["total_percent"]
    if percent is None:
        return (f"{hard} hard days and {rest} rest days are planned. Load: No data ({week['sync']}).",
                ({"label": "Hard days", "value": str(hard)}, {"label": "Rest days", "value": str(rest)}))
    return (f"This week has {hard} hard days and {rest} rest days. "
            f"With the plan, load is {percent}% of usual.",
            ({"label": "Hard days", "value": str(hard)},
             {"label": "Load", "value": f"{percent}% of usual"},
             {"label": "Rest days", "value": str(rest)}))
