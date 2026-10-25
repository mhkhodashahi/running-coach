"""Read plan weeks and dispatch explicit athlete-approved plan actions."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from typing import Any

from coach.planning import apply_draft, load_model, propose_week, revise_week, week_load_breakdown
from coach.proposals import (
    apply,
    dismiss,
    get_proposal,
    get_week,
    list_commitments,
    list_proposals,
    list_protected_habits,
    manual_session,
    monday,
    save_commitment,
    save_protected_habit,
    skip_manual_session,
    undo_last,
)
from config import Settings
from metrics import get_daily_snapshot
from metrics.sports import RECOMMENDABLE_SPORTS, sport_category
from web.formatting import duration_minutes, short_date
from web.today import sync_label


def _groups(proposal: dict[str, Any]) -> list[dict[str, Any]]:
    facts = {fact["id"]: fact for fact in proposal["facts"]}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for change in proposal["changes"]:
        grouped.setdefault(change["group_id"] or str(change["id"]), []).append(change)
    return [{"id": group_id, "changes": changes,
             "title": _change_title(changes[0]),
             "evidence": list({fact_id: facts[fact_id] for change in changes
                               for fact_id in change["fact_ids"] if fact_id in facts}.values())}
            for group_id, changes in grouped.items()]


def _change_title(change: dict[str, Any]) -> str:
    session = change["session"]
    sport = "run" if session["sport"] == "running" else session["sport"]
    prefix = "Remove " if change["change_type"] == "remove" else ""
    return (f"{short_date(session['date'])} — {prefix}{session['intent'].title()} {sport} "
            f"{session['duration_min']} min")


def _actuals(settings: Settings, day: date, start: date) -> tuple[dict[str, list[dict[str, Any]]], set[str]]:
    snapshot = get_daily_snapshot(day, database=settings.db_path, user_id=settings.default_user_id,
                                  timezone=settings.local_timezone, sleep_goal_hours=settings.sleep_goal_hours,
                                  hr_zones=settings.hr_zones)
    loads = {item.activity_id: item.load.value for item in snapshot.sessions}
    actuals: dict[str, list[dict[str, Any]]] = {}
    rest_choices: set[str] = set()
    with sqlite3.connect(settings.db_path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        for row in connection.execute("SELECT id,date,type,duration FROM activities WHERE user_id=? "
                                      "AND substr(date,1,10) BETWEEN ? AND ? ORDER BY date,id",
                                      (settings.default_user_id, start.isoformat(), day.isoformat())):
            stamp = row["date"][:10]
            sport = sport_category(row["type"], date.fromisoformat(stamp))
            if sport not in RECOMMENDABLE_SPORTS:
                continue
            actuals.setdefault(stamp, []).append({"id": row["id"], "sport": sport,
                "duration": duration_minutes(row["duration"]), "load": loads.get(row["id"]), "status": "done"})
        for row in connection.execute("SELECT decision_date,payload_json FROM coaching_decisions "
                                      "WHERE user_id=? AND decision_type='daily_v2' AND decision_date BETWEEN ? AND ?",
                                      (settings.default_user_id, start.isoformat(), day.isoformat())):
            try:
                if json.loads(row["payload_json"]).get("athlete_choice") == "rest":
                    rest_choices.add(row["decision_date"])
            except (ValueError, TypeError):
                continue
    return actuals, rest_choices


def _week_view(sessions: list[dict[str, Any]], model: Any, start: date, today: date,
               actuals: dict[str, list[dict[str, Any]]], rest_choices: set[str]) -> dict[str, Any]:
    breakdown = week_load_breakdown(sessions, model, start)
    days = []
    actual_total = 0.0
    planned_total = 0.0
    known = True
    for item in breakdown["days"]:
        current = date.fromisoformat(item["date"])
        recorded = actuals.get(item["date"], [])
        actual_values = [activity["load"] for activity in recorded]
        actual_load = sum(actual_values) if all(value is not None for value in actual_values) else None
        future_sessions = [session for session in item["sessions"] if current >= today and
                           session.get("linked_activity_id") is None]
        future = week_load_breakdown(future_sessions, model, current)["days"][0]["estimated_load"]
        if current > today:
            actual_load = 0.0
        if current < today:
            future = 0.0
        if actual_load is None or future is None:
            known = False
        else:
            actual_total += actual_load
            planned_total += future
        total = actual_load + future if actual_load is not None and future is not None else None
        shown_sessions = [session for session in sessions if session["date"] == item["date"]]
        days.append({**item, "sessions": shown_sessions, "label": short_date(current), "today": current == today,
                     "past": current < today, "actuals": recorded, "actual_load": actual_load,
                     "planned_load": future, "estimated_load": total,
                     "empty_label": "Rest day" if item["date"] in rest_choices else "Nothing planned"})
    return {"days": days, "actual_total": actual_total if known else None,
            "planned_total": planned_total if known else None,
            "weekly_total": actual_total + planned_total if known else None,
            "expected_walking_weekly": breakdown["expected_walking_weekly"], "cap": breakdown["cap"]}


def _mobile_rows(days: list[dict[str, Any]]) -> list[dict[str, Any]]:
    past = [item for item in days if item["past"]]
    rows = []
    if past:
        count = sum(len(item["actuals"]) for item in past)
        loads = [item["actual_load"] for item in past]
        total = round(sum(loads)) if all(value is not None for value in loads) else None
        load_label = f"{total} TRIMP" if total is not None else "load unavailable"
        rows.append({"kind": "summary", "label": f"{past[0]['label']}–{past[-1]['label']}: "
                     f"{count} session{'s' if count != 1 else ''}, {load_label}"})
    future = [item for item in days if not item["past"]]
    empty: list[dict[str, Any]] = []
    def flush() -> None:
        if empty:
            label = (f"{empty[0]['label']}–{empty[-1]['label']}" if len(empty) > 1 else empty[0]["label"])
            rows.append({"kind": "empty", "label": f"{label}: Nothing planned"})
            empty.clear()
    for item in future:
        if not item["sessions"] and not item["actuals"] and item["empty_label"] == "Nothing planned":
            empty.append(item)
        else:
            flush()
            rows.append({"kind": "day", "day": item})
    flush()
    return rows


def plan_context(settings: Settings, day: date, *, notice: str | None = None,
                 error: str | None = None) -> dict[str, Any]:
    """Render this and next week without changing the plan."""
    start = monday(day)
    actuals, rest_choices = _actuals(settings, day, start)
    weeks = []
    for offset in (0, 7):
        week_start = start + timedelta(days=offset)
        week = get_week(settings.db_path, settings.default_user_id, week_start)
        model = load_model(settings.db_path, settings.default_user_id, week_start, settings)
        breakdown = _week_view(week["sessions"], model, week_start, day, actuals, rest_choices)
        proposals = list_proposals(settings.db_path, settings.default_user_id, week_start)
        days = breakdown["days"]
        label = next(("Lighter week" if "lighter week" in proposal["summary"].lower() else
                      "Full week" if "full week" in proposal["summary"].lower() else None
                      for proposal in proposals if proposal["status"] in ("pending", "applied", "partially_applied")
                      and ("lighter week" in proposal["summary"].lower()
                           or "full week" in proposal["summary"].lower())), None)
        proposed = []
        for proposal in proposals:
            projection = None
            if proposal["status"] == "pending":
                try:
                    candidate = apply_draft(week["sessions"], proposal["changes"])
                    projection = _week_view(candidate, model, week_start, day, actuals,
                                            rest_choices)["weekly_total"]
                except ValueError:
                    pass
            proposed.append({**proposal, "groups": _groups(proposal), "projected_total": projection})
        weeks.append({"start": week_start.isoformat(), "label": short_date(week_start),
                      "days": days, "total": breakdown["weekly_total"], "cap": breakdown["cap"],
                      "actual_total": breakdown["actual_total"], "planned_total": breakdown["planned_total"],
                      "expected_walking": breakdown["expected_walking_weekly"], "week_label": label,
                      "mobile_rows": _mobile_rows(days),
                      "bar_percent": min(100, round(breakdown["weekly_total"] / breakdown["cap"] * 100))
                      if breakdown["cap"] and breakdown["weekly_total"] is not None else None,
                      "actual_percent": min(100, round(breakdown["actual_total"] / breakdown["cap"] * 100))
                      if breakdown["cap"] and breakdown["actual_total"] is not None else None,
                      "proposals": proposed})
    return {"weeks": weeks, "commitments": list_commitments(settings.db_path, settings.default_user_id),
            "habits": list_protected_habits(settings.db_path, settings.default_user_id),
            "notice": notice, "error": error, "sync": sync_label(settings, day),
            "weekdays": tuple(enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"))),
            "pending_proposals": any(proposal["status"] == "pending" for week in weeks
                                     for proposal in week["proposals"])}


def create_week(settings: Settings, day: date, start: date, llm: Any = None) -> dict[str, Any]:
    return propose_week(start, settings=settings, user_id=settings.default_user_id, llm=llm, today=day)


def apply_groups(settings: Settings, proposal_id: int, group_ids: list[str]) -> dict[str, Any]:
    proposal = get_proposal(settings.db_path, settings.default_user_id, proposal_id)
    if proposal["status"] != "pending":
        raise ValueError("Proposal is stale or no longer pending; request a fresh proposal")
    groups = _groups(proposal)
    known = {item["id"] for item in groups}
    if set(group_ids) - known:
        raise ValueError("Unknown change group")
    accepted = [change["id"] for group in groups if group["id"] in group_ids
                for change in group["changes"]]
    return apply(settings.db_path, settings.default_user_id, proposal_id, accepted)


def dismiss_proposal(settings: Settings, proposal_id: int) -> None:
    dismiss(settings.db_path, settings.default_user_id, proposal_id)


def revise_proposal(settings: Settings, day: date, proposal_id: int, text: str,
                    llm: Any = None) -> dict[str, Any]:
    return revise_week(proposal_id, text, settings=settings, user_id=settings.default_user_id,
                       llm=llm, today=day)


def fresh_proposal(settings: Settings, day: date, proposal_id: int, llm: Any = None) -> dict[str, Any]:
    old = get_proposal(settings.db_path, settings.default_user_id, proposal_id)
    if not old["changes"]:
        raise ValueError("Proposal has no dated changes")
    start = date.fromisoformat(old["changes"][0]["session"]["date"])
    return create_week(settings, day, start, llm)


def undo_coach_change(settings: Settings) -> dict[str, Any]:
    return undo_last(settings.db_path, settings.default_user_id)


def edit_plan_item(settings: Settings, kind: str, data: dict[str, str]) -> None:
    """Validate form primitives, then use the version-bumping athlete APIs."""
    user_id = settings.default_user_id
    identifier = int(data["id"]) if data.get("id") else None
    if kind == "commitment":
        save_commitment(settings.db_path, user_id, weekday=int(data["weekday"]),
                        start_time=data["start_time"], sport=data["sport"], kind=data["kind"],
                        duration_min=int(data["duration_min"]), active=data.get("active") == "on",
                        commitment_id=identifier)
    elif kind == "habit":
        save_protected_habit(settings.db_path, user_id, sport=data["sport"], intent=data["intent"],
                             duration_min=int(data["duration_min"]), per_week=int(data["per_week"]),
                             active=data.get("active") == "on", habit_id=identifier)
    elif kind == "session":
        manual_session(settings.db_path, user_id, {
            "date": data["date"], "sport": data["sport"], "intent": data["intent"],
            "duration_min": int(data["duration_min"]),
            "hr_cap_bpm": int(data["hr_cap_bpm"]) if data.get("hr_cap_bpm") else None,
            "notes": data.get("notes") or None}, session_id=identifier)
    elif kind == "remove_session" and identifier is not None:
        skip_manual_session(settings.db_path, user_id, identifier)
    else:
        raise ValueError("Unknown plan editor")
