"""Versioned, athlete-approved plan changes. No coach path writes a plan without apply()."""

from __future__ import annotations

import json
import re
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from db.repositories.plan import PlanRepository
from db.session import session_scope
from metrics.sports import sport_category
from services.number_verifier import verify_numbers

SPORTS = frozenset({"running", "gym", "football", "volleyball", "mobility"})
TEAM_SPORTS = frozenset({"football", "volleyball"})
SUPPRESS_PROPOSAL_NOTICE: ContextVar[bool] = ContextVar("suppress_proposal_notice", default=False)
SESSION_FIELDS = ("id", "user_id", "date", "sport", "intent", "duration_min", "hr_cap_bpm",
                  "notes", "workout_type", "workout_json", "origin", "status", "linked_activity_id",
                  "fixed_commitment_id")


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat()


def monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


@contextmanager
def _repository(database: Path, *, immediate: bool = False) -> Iterator[PlanRepository]:
    with session_scope(f"sqlite:///{database.resolve()}") as session:
        repository = PlanRepository(session)
        if immediate:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        yield repository


def _version(repository: PlanRepository, user_id: int) -> int:
    return repository.version(user_id)


def _bump(repository: PlanRepository, user_id: int) -> int:
    return repository.bump_version(user_id)


def _rows(repository: PlanRepository, user_id: int, start: date) -> list[dict[str, Any]]:
    sessions = repository.week_sessions(user_id, start)
    for row in repository.week_mobility_sessions(user_id, start):
        item = dict(row)
        item["id"] = -item["id"]
        item["linked_activity_id"] = None
        item["fixed_commitment_id"] = None
        sessions.append(item)
    return sorted(sessions, key=lambda item: (item["date"], item["id"]))


def _virtual_fixed(repository: PlanRepository, user_id: int, start: date,
                   existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    materialized = {row["fixed_commitment_id"] for row in existing}
    result = []
    for row in repository.fixed_commitments(user_id, active_only=True):
        if row["id"] in materialized:
            continue
        result.append({"id": None, "user_id": user_id,
                       "date": (start + timedelta(days=row["weekday"])).isoformat(),
                       "sport": row["sport"], "intent": row["kind"],
                       "duration_min": row["typical_duration_min"], "hr_cap_bpm": None,
                       "notes": f"{row['start_time']} fixed {row['kind']}", "origin": "fixed",
                       "status": "planned", "linked_activity_id": None,
                       "fixed_commitment_id": row["id"]})
    return result


def _virtual_protected(repository: PlanRepository, user_id: int, start: date,
                       existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project recurring athlete habits to stable non-team days, one per day."""
    team_days = {item["date"] for item in existing if item.get("origin") == "fixed" and
                 item.get("status", "planned") == "planned"}
    order = (0, 2, 4, 6, 1, 3, 5)
    available = [start + timedelta(days=offset) for offset in order]
    available.sort(key=lambda day: day.isoformat() in team_days)
    habits = repository.protected_habits(user_id, active_only=True)
    if sum(row["per_week"] for row in habits) > 7:
        raise ValueError("More than seven protected sessions cannot fit in one week")
    result = []
    for habit in habits:
        for _ in range(habit["per_week"]):
            day = available.pop(0)
            result.append({"id": None, "user_id": user_id, "date": day.isoformat(),
                           "sport": habit["sport"], "intent": habit["intent"],
                           "duration_min": habit["duration_min"], "hr_cap_bpm": None,
                           "notes": "Protected habit", "origin": "protected", "status": "planned",
                           "linked_activity_id": None, "fixed_commitment_id": None,
                           "protected_habit_id": habit["id"]})
    return result


def match_completed_sessions(sessions: list[dict[str, Any]],
                             activities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Annotate a plan view without changing persisted plan rows."""
    matched = [dict(item) for item in sessions]
    used = {item["linked_activity_id"] for item in matched if item.get("linked_activity_id") is not None}
    for item in matched:
        if item.get("status") != "planned" or item["sport"] in ("mobility", "rest"):
            continue
        activity = next((row for row in activities if row["id"] not in used and row["date"] == item["date"] and
                         row["sport"] == item["sport"]), None)
        if activity is not None:
            item["status"] = "done"
            item["linked_activity_id"] = activity["id"]
            used.add(activity["id"])
    return matched


def get_week(database: Path, user_id: int, start: date) -> dict[str, Any]:
    start = monday(start)
    with _repository(database) as repository:
        sessions = _rows(repository, user_id, start)
        sessions.extend(_virtual_fixed(repository, user_id, start, sessions))
        sessions.extend(_virtual_protected(repository, user_id, start, sessions))
        sessions.sort(key=lambda item: (item["date"], item["id"] or 0))
        activities = [{"id": row["id"], "date": str(row["date"])[:10],
                       "sport": sport_category(row["type"], start)}
                      for row in repository.week_activities(user_id, start)]
        sessions = match_completed_sessions(sessions, activities)
        return {"week_start": start.isoformat(), "version": _version(repository, user_id), "sessions": sessions}


def list_commitments(database: Path, user_id: int) -> list[dict[str, Any]]:
    with _repository(database) as repository:
        return repository.fixed_commitments(user_id)


def list_protected_habits(database: Path, user_id: int) -> list[dict[str, Any]]:
    with _repository(database) as repository:
        return repository.protected_habits(user_id)


def save_protected_habit(database: Path, user_id: int, *, sport: str, intent: str,
                         duration_min: int, per_week: int, active: bool = True,
                         habit_id: int | None = None) -> int:
    if sport not in ("running", "gym", "football", "volleyball") or not 1 <= len(intent) <= 32:
        raise ValueError("Invalid protected sport or intent")
    if not 15 <= duration_min <= 300 or not 1 <= per_week <= 7:
        raise ValueError("Protected duration must be 15-300 minutes and frequency 1-7 per week")
    with _repository(database, immediate=True) as repository:
        existing = repository.protected_habit_counts(user_id)
        total = sum(row["per_week"] for row in existing if row["id"] != habit_id) + (per_week if active else 0)
        if total > 7:
            raise ValueError("Protected habits cannot exceed seven sessions per week")
        if habit_id is None:
            habit_id = repository.insert_protected_habit(
                user_id, sport, intent, duration_min, per_week, active
            )
        else:
            if not repository.update_protected_habit(
                    user_id, habit_id, sport, intent, duration_min, per_week, active):
                raise ValueError("Protected habit not found")
        _bump(repository, user_id)
    return habit_id


def _materialize(repository: PlanRepository, user_id: int, start: date) -> int:
    existing = _rows(repository, user_id, start)
    missing = _virtual_fixed(repository, user_id, start, existing)
    for item in missing:
        _insert_session(repository, item)
    return len(missing)


def materialize_week(database: Path, user_id: int, start: date) -> int:
    """Create dated copies of recurring commitments before drafting a week."""
    with _repository(database, immediate=True) as repository:
        added = _materialize(repository, user_id, monday(start))
        if added:
            _bump(repository, user_id)
        return added


def _validate_session(item: dict[str, Any]) -> None:
    date.fromisoformat(item["date"])
    if item["sport"] not in SPORTS or not 15 <= int(item["duration_min"]) <= 300:
        raise ValueError("Invalid planned sport or duration")
    if item["sport"] == "mobility" and (item["intent"] != "recovery" or
            not 15 <= int(item["duration_min"]) <= 20 or item.get("hr_cap_bpm") is not None):
        raise ValueError("Mobility is non-training recovery for 15-20 minutes without an HR cap")
    if item.get("hr_cap_bpm") is not None and not 60 <= int(item["hr_cap_bpm"]) <= 240:
        raise ValueError("HR cap must be 60-240 bpm")
    if len(str(item.get("notes") or "")) > 500:
        raise ValueError("Plan notes are too long")
    if item.get("status", "planned") not in ("planned", "done", "skipped"):
        raise ValueError("Invalid plan status")
    if item["sport"] == "mobility" and item.get("status", "planned") == "done":
        raise ValueError("Non-training mobility is not linked as a logged activity")


def _insert_session(repository: PlanRepository, item: dict[str, Any]) -> int:
    _validate_session(item)
    stamp = _now()
    return repository.insert_session(item, stamp)


def save_commitment(database: Path, user_id: int, *, weekday: int, start_time: str,
                    sport: str, kind: str, duration_min: int, active: bool = True,
                    commitment_id: int | None = None) -> int:
    if weekday not in range(7) or len(start_time) != 5 or sport not in TEAM_SPORTS or kind not in ("training", "match"):
        raise ValueError("Invalid fixed team commitment")
    if not 15 <= duration_min <= 300:
        raise ValueError("Invalid commitment duration")
    with _repository(database, immediate=True) as repository:
        if commitment_id is None:
            commitment_id = repository.insert_fixed_commitment(
                user_id, weekday, start_time, sport, kind, duration_min, active
            )
        else:
            old = repository.fixed_commitment(user_id, commitment_id)
            if old is None:
                raise ValueError("Commitment not found")
            if not repository.update_fixed_commitment(
                    user_id, commitment_id, weekday, start_time, sport, kind, duration_min, active):
                raise ValueError("Commitment not found")
            existing = repository.commitment_sessions(user_id, commitment_id)
            for planned in existing:
                moved = monday(date.fromisoformat(planned["date"])) + timedelta(days=weekday)
                status = "skipped" if not active else "planned" if not old["active"] else planned["status"]
                repository.update_committed_session(
                    user_id, planned["id"], moved, sport, kind, duration_min, status, _now()
                )
        _bump(repository, user_id)
    return commitment_id


def manual_session(database: Path, user_id: int, item: dict[str, Any], *, session_id: int | None = None) -> int:
    """Direct athlete edit; fixed sessions and logged sessions are immutable here."""
    item = {**item, "user_id": user_id, "origin": "athlete", "status": "planned"}
    _validate_session(item)
    with _repository(database, immediate=True) as repository:
        if session_id is None:
            session_id = _insert_session(repository, item)
        else:
            row = repository.planned_session(user_id, session_id)
            if row is None or row["origin"] == "fixed" or row["status"] == "done":
                raise ValueError("Fixed or logged sessions cannot be edited here")
            repository.update_plan_session(user_id, session_id, item, _now(), include_workout=False)
        _bump(repository, user_id)
    return session_id


def skip_manual_session(database: Path, user_id: int, session_id: int) -> None:
    """Athlete removes an unlogged non-fixed session from the active plan."""
    with _repository(database, immediate=True) as repository:
        if not repository.skip_plan_session(user_id, session_id, _now()):
            raise ValueError("Only an unlogged non-fixed session can be skipped")
        _bump(repository, user_id)


def _proposal_view(repository: PlanRepository, row: dict[str, Any]) -> dict[str, Any]:
    changes = repository.proposal_changes(row["id"])
    for change in changes:
        change["session"] = json.loads(change.pop("session_json"))
        change["fact_ids"] = json.loads(change.pop("fact_ids_json"))
        if change.get("workout_json") and not change["session"].get("workout"):
            change["session"]["workout"] = json.loads(change["workout_json"])
    result = dict(row)
    result["facts"] = json.loads(result.pop("facts_json"))
    result["changes"] = changes
    if result["status"] == "pending" and result["base_version"] != _version(repository, result["user_id"]):
        result["status"] = "stale"
    return result


def get_proposal(database: Path, user_id: int, proposal_id: int) -> dict[str, Any]:
    with _repository(database) as repository:
        row = repository.proposal(user_id, proposal_id)
        if row is None:
            raise ValueError("Proposal not found")
        return _proposal_view(repository, row)


def list_proposals(database: Path, user_id: int, start: date) -> list[dict[str, Any]]:
    with _repository(database) as repository:
        rows = repository.proposals_for_week(user_id, start)
        return [_proposal_view(repository, row) for row in rows]


def _validate_changes(kind: str, facts: list[dict[str, str]], changes: list[dict[str, Any]]) -> None:
    if kind not in ("weekly_plan", "change") or not changes or len(changes) > 14:
        raise ValueError("A proposal needs 1-14 changes")
    known = {fact["id"] for fact in facts}
    for change in changes:
        item = change["session"]
        if change["change_type"] not in ("add", "modify", "remove") or not change["reason"].strip():
            raise ValueError("Invalid proposal change")
        if not change["fact_ids"] or set(change["fact_ids"]) - known:
            raise ValueError("Each change must cite known facts")
        if verify_numbers(facts, change["reason"]).unmatched:
            raise ValueError("Proposal reason contains a number absent from its facts")
        if re.search(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b", change["reason"]):
            raise ValueError("Fact IDs belong in fact_ids, not in the reason")
        _validate_session(item)
        if item.get("workout") is not None:
            from coach.workouts import TEMPLATES

            workout = item["workout"]
            if (not isinstance(workout, dict) or workout.get("type") not in TEMPLATES or
                    item.get("workout_type", workout.get("type")) != workout.get("type") or
                    workout.get("duration_min") != item["duration_min"] or
                    TEMPLATES[workout["type"]].sport != item["sport"]):
                raise ValueError("Structured workout does not match the session")
        group_id = change.get("group_id")
        if group_id is not None and (not isinstance(group_id, str) or not 1 <= len(group_id) <= 64 or
                                     re.fullmatch(r"[A-Za-z0-9_-]+", group_id) is None):
            raise ValueError("Invalid proposal group ID")


def _insert_proposal(repository: PlanRepository, user_id: int, kind: str, summary: str,
                     facts: list[dict[str, str]], changes: list[dict[str, Any]], version: int) -> int:
    return repository.insert_proposal(user_id, kind, summary, facts, changes, version, _now())


def create_proposal(database: Path, user_id: int, kind: str, summary: str,
                    facts: list[dict[str, str]], changes: list[dict[str, Any]], *,
                    base_version: int | None = None) -> dict[str, Any]:
    _validate_changes(kind, facts, changes)
    with _repository(database, immediate=True) as repository:
        current = _version(repository, user_id)
        if base_version is not None and base_version != current:
            raise ValueError("Plan changed while drafting; request a fresh proposal")
        proposal_id = _insert_proposal(repository, user_id, kind, summary, facts, changes, current)
    result = get_proposal(database, user_id, proposal_id)
    _notify_created(database, user_id, summary)
    return result


def _notify_created(database: Path, user_id: int, summary: str) -> None:
    if SUPPRESS_PROPOSAL_NOTICE.get():
        return
    from config import get_settings
    from services.telegram_service import TelegramService

    settings = get_settings()
    if (database.resolve() != settings.db_path.resolve() or user_id != settings.default_user_id or
            not settings.telegram_bot_token or not settings.telegram_chat_id):
        return
    try:
        TelegramService(settings).send_text(f"Coach proposal: {summary[:120]}. Review it in the app.")
    except Exception:
        warnings.warn("Coach proposal saved, but Telegram notification failed.", RuntimeWarning, stacklevel=2)


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in SESSION_FIELDS}


def apply(database: Path, user_id: int, proposal_id: int, accepted_change_ids: list[int]) -> dict[str, Any]:
    """One transaction: stale check, snapshot, selected edits, decisions, version bump."""
    selected = set(accepted_change_ids)
    with _repository(database, immediate=True) as repository:
        proposal = repository.proposal(user_id, proposal_id)
        if proposal is None or proposal["status"] != "pending":
            raise ValueError("Proposal is not pending")
        current = _version(repository, user_id)
        if current != proposal["base_version"]:
            repository.mark_stale(proposal_id)
            repository.commit()
            raise ValueError("Proposal is stale because the plan changed. Request a fresh proposal.")
        changes = repository.proposal_changes(proposal_id)
        ids = {row["id"] for row in changes}
        if selected - ids:
            raise ValueError("Unknown change ID")
        groups: dict[str, set[int]] = {}
        for row in changes:
            groups.setdefault(row["group_id"] or f"legacy-{row['id']}", set()).add(row["id"])
        if any(selected & members and not members <= selected for members in groups.values()):
            raise ValueError("Select or reject every change in a dependency group together")
        if selected:
            from coach.planning import apply_draft, load_model, validate_week
            from config import get_settings
            from services.daily_decision_service import build_daily_decision

            settings = replace(get_settings(), db_path=database)
            now = datetime.now(ZoneInfo(settings.local_timezone)).date()
            by_week: dict[date, list[dict[str, Any]]] = {}
            for row in changes:
                if row["id"] in selected:
                    item = json.loads(row["session_json"])
                    by_week.setdefault(monday(date.fromisoformat(item["date"])), []).append(
                        {"change_type": row["change_type"], "session": item})
            decisions = {}
            for day in (now, now + timedelta(days=1)):
                decisions[day] = build_daily_decision(day, database, user_id, settings.local_timezone,
                                                      settings.sleep_goal_hours, settings.hr_zones).intensity
            for start, proposed in by_week.items():
                before = _rows(repository, user_id, start)
                before.extend(_virtual_fixed(repository, user_id, start, before))
                before.extend(_virtual_protected(repository, user_id, start, before))
                candidate = apply_draft(before, proposed, allow_fixed_daily=proposal["kind"] == "change")
                for change in proposed:
                    item = change["session"]
                    if change["change_type"] == "add":
                        continue
                    target = next((row for row in before if row.get("id") == item.get("id")), None)
                    if target is None or target.get("status") == "done":
                        raise ValueError("Target session is missing or logged")
                    if (target["sport"] == "mobility") != (item["sport"] == "mobility"):
                        raise ValueError("Changing between training and mobility requires remove and add")
                    if target["origin"] == "fixed":
                        decision = decisions.get(date.fromisoformat(item["date"]))
                        daily_allowed = (proposal["kind"] == "change" and change["change_type"] == "modify" and
                                         item["date"] == now.isoformat() and item["sport"] == target["sport"] and
                                         item["duration_min"] == target["duration_min"] and
                                         ((decision == "easy" and item["intent"] == "skills only" and
                                           item.get("status", "planned") == "planned") or
                                          (decision == "rest" and item.get("status") == "skipped")))
                        if not daily_allowed:
                            raise ValueError("Fixed commitments are immutable in weekly plans")
                errors = validate_week(candidate, load_model(database, user_id, start, settings),
                                       today=now, decisions=decisions, week_start=start)
                if errors:
                    raise ValueError("Unsafe plan change: " + "; ".join(errors))
        affected: dict[str, list[dict[str, Any]]] = {}
        for row in changes:
            if row["id"] not in selected:
                continue
            item = json.loads(row["session_json"])
            start = monday(date.fromisoformat(item["date"]))
            affected.setdefault(start.isoformat(), _rows(repository, user_id, start))
            target = None
            if row["change_type"] != "add":
                target = repository.any_session(user_id, int(item.get("id") or 0))
                if target is None or target["status"] == "done":
                    raise ValueError("Target session is missing or logged")
                if row["change_type"] == "modify" and item["date"] != target["date"]:
                    raise ValueError("Moving a session requires remove and add changes")
            if row["change_type"] == "add":
                _insert_session(repository, {**item, "user_id": user_id, "origin": "coach"})
            elif row["change_type"] == "modify":
                _validate_session(item)
                if item["sport"] == "mobility":
                    repository.update_mobility_session(user_id, -int(item["id"]), item, _now())
                else:
                    repository.update_plan_session(user_id, int(item["id"]), item, _now())
            else:
                repository.change_plan_session_status(user_id, int(item["id"]), "skipped", _now())
        if selected:
            new_version = _bump(repository, user_id)
            snapshot = {start: {"before": [_public_row(item) for item in before],
                                "after": [_public_row(item) for item in _rows(repository, user_id, date.fromisoformat(start))]}
                        for start, before in affected.items()}
            repository.save_snapshot(user_id, current, new_version, json.dumps(snapshot, sort_keys=True),
                                     f"coach proposal {proposal_id}", _now())
        repository.proposal_changes_decisions(proposal_id, changes, selected)
        status = ("applied" if len(selected) == len(changes) else "partially_applied" if selected else "dismissed")
        repository.update_proposal_status(proposal_id, status)
    return get_proposal(database, user_id, proposal_id)


def dismiss(database: Path, user_id: int, proposal_id: int) -> None:
    with _repository(database) as repository:
        if not repository.mark_dismissed(user_id, proposal_id):
            raise ValueError("Proposal is not pending")


def request_revision(database: Path, user_id: int, proposal_id: int, text: str,
                     replacement: list[dict[str, Any]]) -> dict[str, Any]:
    """Store revised draft; caller supplies validated replacements from the planner."""
    if not 1 <= len(text.strip()) <= 500:
        raise ValueError("Give a short revision request")
    with _repository(database, immediate=True) as repository:
        old = repository.proposal(user_id, proposal_id)
        if old is None or old["status"] != "pending" or old["base_version"] != _version(repository, user_id):
            raise ValueError("Proposal is stale or no longer pending")
        facts = json.loads(old["facts_json"])
        _validate_changes(old["kind"], facts, replacement)
        new_id = _insert_proposal(repository, user_id, old["kind"], text.strip(), facts,
                                  replacement, old["base_version"])
        repository.mark_superseded(proposal_id)
    result = get_proposal(database, user_id, new_id)
    _notify_created(database, user_id, text.strip())
    return result


def undo_last(database: Path, user_id: int) -> dict[str, Any]:
    """Restore only affected plan rows when unchanged since approval."""
    with _repository(database, immediate=True) as repository:
        record = repository.latest_snapshot(user_id)
        if record is None:
            raise ValueError("No coach changes to undo")
        snapshot = json.loads(record["snapshot_json"])
        for start, state in snapshot.items():
            current = [_public_row(item) for item in _rows(repository, user_id, date.fromisoformat(start))]
            before = {item["id"]: item for item in state["before"]}
            after = {item["id"]: item for item in state["after"]}
            current_by_id = {item["id"]: item for item in current}
            touched = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
            if any(current_by_id.get(key) != after.get(key) for key in touched):
                raise ValueError("An affected plan session changed after approval; undo will not overwrite it")
        for state in snapshot.values():
            before = {item["id"]: item for item in state["before"]}
            after = {item["id"]: item for item in state["after"]}
            for key in before.keys() | after.keys():
                if before.get(key) == after.get(key):
                    continue
                if key not in before:
                    repository.delete_session(user_id, key)
                elif key not in after:
                    repository.restore_session(user_id, before[key], _now())
                else:
                    repository.restore_existing_session(user_id, key, before[key], _now())
        repository.mark_snapshot_undone(record["id"], _now())
        version = _bump(repository, user_id)
    return {"undone_snapshot_id": record["id"], "version": version}


def link_activity(repository: PlanRepository, user_id: int, activity_id: int,
                  day: date, sport: str) -> bool:
    """Link a newly imported activity using the caller's existing transaction."""
    return repository.link_activity(user_id, activity_id, day, sport, _now())
