"""Versioned, athlete-approved plan changes. No coach path writes a plan without apply()."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from services.coach_facts import unsupported_text_numbers

SPORTS = frozenset({"running", "gym", "football", "volleyball"})
TEAM_SPORTS = frozenset({"football", "volleyball"})
SESSION_FIELDS = ("id", "user_id", "date", "sport", "intent", "duration_min", "hr_cap_bpm",
                  "notes", "origin", "status", "linked_activity_id", "fixed_commitment_id")


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat()


def monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


@contextmanager
def _db(database: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(database, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _version(connection: sqlite3.Connection, user_id: int) -> int:
    row = connection.execute("SELECT version FROM plan_versions WHERE user_id=?", (user_id,)).fetchone()
    return row[0] if row else 0


def _bump(connection: sqlite3.Connection, user_id: int) -> int:
    connection.execute("INSERT INTO plan_versions(user_id,version) VALUES(?,1) "
                       "ON CONFLICT(user_id) DO UPDATE SET version=version+1", (user_id,))
    return _version(connection, user_id)


def _rows(connection: sqlite3.Connection, user_id: int, start: date) -> list[dict[str, Any]]:
    end = start + timedelta(days=7)
    return [dict(row) for row in connection.execute(
        "SELECT * FROM plan_sessions WHERE user_id=? AND date>=? AND date<? ORDER BY date,id",
        (user_id, start.isoformat(), end.isoformat()))]


def _virtual_fixed(connection: sqlite3.Connection, user_id: int, start: date,
                   existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    materialized = {row["fixed_commitment_id"] for row in existing}
    result = []
    for row in connection.execute("SELECT * FROM fixed_commitments WHERE user_id=? AND active=1", (user_id,)):
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


def get_week(database: Path, user_id: int, start: date) -> dict[str, Any]:
    start = monday(start)
    with _db(database) as connection:
        sessions = _rows(connection, user_id, start)
        sessions.extend(_virtual_fixed(connection, user_id, start, sessions))
        sessions.sort(key=lambda item: (item["date"], item["id"] or 0))
        return {"week_start": start.isoformat(), "version": _version(connection, user_id), "sessions": sessions}


def list_commitments(database: Path, user_id: int) -> list[dict[str, Any]]:
    with _db(database) as connection:
        return [dict(row) for row in connection.execute(
            "SELECT * FROM fixed_commitments WHERE user_id=? ORDER BY weekday,start_time,id", (user_id,))]


def _materialize(connection: sqlite3.Connection, user_id: int, start: date) -> int:
    existing = _rows(connection, user_id, start)
    missing = _virtual_fixed(connection, user_id, start, existing)
    for item in missing:
        _insert_session(connection, item)
    return len(missing)


def materialize_week(database: Path, user_id: int, start: date) -> int:
    """Create dated copies of recurring commitments before drafting a week."""
    with _db(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        added = _materialize(connection, user_id, monday(start))
        if added:
            _bump(connection, user_id)
        return added


def _validate_session(item: dict[str, Any]) -> None:
    date.fromisoformat(item["date"])
    if item["sport"] not in SPORTS or not 15 <= int(item["duration_min"]) <= 300:
        raise ValueError("Invalid planned sport or duration")
    if item.get("hr_cap_bpm") is not None and not 60 <= int(item["hr_cap_bpm"]) <= 240:
        raise ValueError("HR cap must be 60-240 bpm")
    if len(str(item.get("notes") or "")) > 500:
        raise ValueError("Plan notes are too long")
    if item.get("status", "planned") not in ("planned", "done", "skipped"):
        raise ValueError("Invalid plan status")


def _insert_session(connection: sqlite3.Connection, item: dict[str, Any]) -> int:
    _validate_session(item)
    stamp = _now()
    cursor = connection.execute(
        "INSERT INTO plan_sessions(user_id,date,sport,intent,duration_min,hr_cap_bpm,notes,origin,status,"
        "linked_activity_id,fixed_commitment_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (item["user_id"], item["date"], item["sport"], item["intent"], item["duration_min"],
         item.get("hr_cap_bpm"), item.get("notes"), item["origin"], item.get("status", "planned"),
         item.get("linked_activity_id"), item.get("fixed_commitment_id"), stamp, stamp))
    return int(cursor.lastrowid)


def save_commitment(database: Path, user_id: int, *, weekday: int, start_time: str,
                    sport: str, kind: str, duration_min: int, active: bool = True,
                    commitment_id: int | None = None) -> int:
    if weekday not in range(7) or len(start_time) != 5 or sport not in TEAM_SPORTS or kind not in ("training", "match"):
        raise ValueError("Invalid fixed team commitment")
    if not 15 <= duration_min <= 300:
        raise ValueError("Invalid commitment duration")
    with _db(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        if commitment_id is None:
            cursor = connection.execute(
                "INSERT INTO fixed_commitments(user_id,weekday,start_time,sport,kind,typical_duration_min,active) "
                "VALUES(?,?,?,?,?,?,?)", (user_id, weekday, start_time, sport, kind, duration_min, int(active)))
            commitment_id = int(cursor.lastrowid)
        else:
            cursor = connection.execute(
                "UPDATE fixed_commitments SET weekday=?,start_time=?,sport=?,kind=?,typical_duration_min=?,active=? "
                "WHERE id=? AND user_id=?", (weekday, start_time, sport, kind, duration_min, int(active),
                                              commitment_id, user_id))
            if cursor.rowcount != 1:
                raise ValueError("Commitment not found")
            connection.execute("UPDATE plan_sessions SET date=date, sport=?,intent=?,duration_min=?,updated_at=? "
                               "WHERE user_id=? AND fixed_commitment_id=? AND status='planned'",
                               (sport, kind, duration_min, _now(), user_id, commitment_id))
        _bump(connection, user_id)
    return commitment_id


def manual_session(database: Path, user_id: int, item: dict[str, Any], *, session_id: int | None = None) -> int:
    """Direct athlete edit; fixed sessions and logged sessions are immutable here."""
    item = {**item, "user_id": user_id, "origin": "athlete", "status": "planned"}
    _validate_session(item)
    with _db(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        if session_id is None:
            session_id = _insert_session(connection, item)
        else:
            row = connection.execute("SELECT origin,status FROM plan_sessions WHERE id=? AND user_id=?",
                                     (session_id, user_id)).fetchone()
            if row is None or row["origin"] == "fixed" or row["status"] == "done":
                raise ValueError("Fixed or logged sessions cannot be edited here")
            connection.execute("UPDATE plan_sessions SET date=?,sport=?,intent=?,duration_min=?,hr_cap_bpm=?,"
                               "notes=?,updated_at=? WHERE id=? AND user_id=?",
                               (item["date"], item["sport"], item["intent"], item["duration_min"],
                                item.get("hr_cap_bpm"), item.get("notes"), _now(), session_id, user_id))
        _bump(connection, user_id)
    return session_id


def _proposal_view(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    changes = [dict(change) for change in connection.execute(
        "SELECT * FROM proposal_changes WHERE proposal_id=? ORDER BY id", (row["id"],))]
    for change in changes:
        change["session"] = json.loads(change.pop("session_json"))
        change["fact_ids"] = json.loads(change.pop("fact_ids_json"))
    result = dict(row)
    result["facts"] = json.loads(result.pop("facts_json"))
    result["changes"] = changes
    if result["status"] == "pending" and result["base_version"] != _version(connection, result["user_id"]):
        result["status"] = "stale"
    return result


def get_proposal(database: Path, user_id: int, proposal_id: int) -> dict[str, Any]:
    with _db(database) as connection:
        row = connection.execute("SELECT * FROM coach_proposals WHERE id=? AND user_id=?",
                                 (proposal_id, user_id)).fetchone()
        if row is None:
            raise ValueError("Proposal not found")
        return _proposal_view(connection, row)


def list_proposals(database: Path, user_id: int, start: date) -> list[dict[str, Any]]:
    end = start + timedelta(days=7)
    with _db(database) as connection:
        rows = connection.execute("SELECT DISTINCT p.* FROM coach_proposals p JOIN proposal_changes c "
                                  "ON c.proposal_id=p.id WHERE p.user_id=? AND "
                                  "json_extract(c.session_json,'$.date')>=? AND "
                                  "json_extract(c.session_json,'$.date')<? ORDER BY p.id DESC LIMIT 20",
                                  (user_id, start.isoformat(), end.isoformat())).fetchall()
        return [_proposal_view(connection, row) for row in rows]


def _validate_changes(kind: str, facts: list[dict[str, str]], changes: list[dict[str, Any]]) -> None:
    if kind not in ("weekly_plan", "change") or not changes or len(changes) > 10:
        raise ValueError("A proposal needs 1-10 changes")
    known = {fact["id"] for fact in facts}
    for change in changes:
        item = change["session"]
        if change["change_type"] not in ("add", "modify", "remove") or not change["reason"].strip():
            raise ValueError("Invalid proposal change")
        if not change["fact_ids"] or set(change["fact_ids"]) - known:
            raise ValueError("Each change must cite known facts")
        if unsupported_text_numbers(change["reason"], facts):
            raise ValueError("Proposal reason contains a number absent from its facts")
        if re.search(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b", change["reason"]):
            raise ValueError("Fact IDs belong in fact_ids, not in the reason")
        _validate_session(item)


def _insert_proposal(connection: sqlite3.Connection, user_id: int, kind: str, summary: str,
                     facts: list[dict[str, str]], changes: list[dict[str, Any]], version: int) -> int:
    cursor = connection.execute("INSERT INTO coach_proposals(user_id,kind,base_version,status,summary,"
                                "facts_json,created_at) VALUES(?,?,?,'pending',?,?,?)",
                                (user_id, kind, version, summary, json.dumps(facts), _now()))
    proposal_id = int(cursor.lastrowid)
    for change in changes:
        connection.execute("INSERT INTO proposal_changes(proposal_id,change_type,session_json,reason,"
                           "fact_ids_json,decision) VALUES(?,?,?,?,?,'pending')",
                           (proposal_id, change["change_type"], json.dumps(change["session"]),
                            change["reason"], json.dumps(change["fact_ids"])))
    return proposal_id


def create_proposal(database: Path, user_id: int, kind: str, summary: str,
                    facts: list[dict[str, str]], changes: list[dict[str, Any]], *,
                    base_version: int | None = None) -> dict[str, Any]:
    _validate_changes(kind, facts, changes)
    with _db(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        current = _version(connection, user_id)
        if base_version is not None and base_version != current:
            raise ValueError("Plan changed while drafting; request a fresh proposal")
        proposal_id = _insert_proposal(connection, user_id, kind, summary, facts, changes, current)
    return get_proposal(database, user_id, proposal_id)


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in SESSION_FIELDS}


def apply(database: Path, user_id: int, proposal_id: int, accepted_change_ids: list[int]) -> dict[str, Any]:
    """One transaction: stale check, snapshot, selected edits, decisions, version bump."""
    selected = set(accepted_change_ids)
    with _db(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        proposal = connection.execute("SELECT * FROM coach_proposals WHERE id=? AND user_id=?",
                                      (proposal_id, user_id)).fetchone()
        if proposal is None or proposal["status"] != "pending":
            raise ValueError("Proposal is not pending")
        current = _version(connection, user_id)
        if current != proposal["base_version"]:
            connection.execute("UPDATE coach_proposals SET status='stale' WHERE id=?", (proposal_id,))
            connection.commit()
            raise ValueError("Proposal is stale because the plan changed. Request a fresh proposal.")
        changes = connection.execute("SELECT * FROM proposal_changes WHERE proposal_id=? ORDER BY id",
                                     (proposal_id,)).fetchall()
        ids = {row["id"] for row in changes}
        if selected - ids:
            raise ValueError("Unknown change ID")
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
                before = _rows(connection, user_id, start)
                before.extend(_virtual_fixed(connection, user_id, start, before))
                candidate = apply_draft(before, proposed)
                errors = validate_week(candidate, load_model(database, user_id, start, settings),
                                       today=now, decisions=decisions)
                if errors:
                    raise ValueError("Unsafe plan change: " + "; ".join(errors))
        affected: dict[str, list[dict[str, Any]]] = {}
        for row in changes:
            if row["id"] not in selected:
                continue
            item = json.loads(row["session_json"])
            start = monday(date.fromisoformat(item["date"]))
            affected.setdefault(start.isoformat(), _rows(connection, user_id, start))
            target = None
            if row["change_type"] != "add":
                target = connection.execute("SELECT * FROM plan_sessions WHERE id=? AND user_id=?",
                                            (item.get("id"), user_id)).fetchone()
                if target is None or target["status"] == "done":
                    raise ValueError("Target session is missing or logged")
                if target["origin"] == "fixed" and row["change_type"] == "remove":
                    raise ValueError("Fixed commitments cannot be silently removed")
                if target["origin"] == "fixed" and row["change_type"] == "modify" and not (
                        item["sport"] == target["sport"] and
                        (item["intent"] == "skills only" or item.get("status") == "skipped")):
                    raise ValueError("A fixed team session may only be lightened to skills only")
            if row["change_type"] == "add":
                _insert_session(connection, {**item, "user_id": user_id, "origin": "coach"})
            elif row["change_type"] == "modify":
                _validate_session(item)
                connection.execute("UPDATE plan_sessions SET sport=?,intent=?,duration_min=?,hr_cap_bpm=?,"
                                   "notes=?,status=?,updated_at=? WHERE id=? AND user_id=?",
                                   (item["sport"], item["intent"], item["duration_min"], item.get("hr_cap_bpm"),
                                    item.get("notes"), item.get("status", target["status"]), _now(),
                                    item["id"], user_id))
            else:
                connection.execute("DELETE FROM plan_sessions WHERE id=? AND user_id=?", (item["id"], user_id))
        if selected:
            new_version = _bump(connection, user_id)
            snapshot = {start: {"before": [_public_row(item) for item in before],
                                "after": [_public_row(item) for item in _rows(connection, user_id, date.fromisoformat(start))]}
                        for start, before in affected.items()}
            connection.execute("INSERT INTO plan_snapshots(user_id,version_before,version_after,snapshot_json,"
                               "reason,created_at) VALUES(?,?,?,?,?,?)",
                               (user_id, current, new_version, json.dumps(snapshot, sort_keys=True),
                                f"coach proposal {proposal_id}", _now()))
        for row in changes:
            connection.execute("UPDATE proposal_changes SET decision=? WHERE id=?",
                               ("accepted" if row["id"] in selected else "rejected", row["id"]))
        status = ("applied" if len(selected) == len(changes) else "partially_applied" if selected else "dismissed")
        connection.execute("UPDATE coach_proposals SET status=? WHERE id=?", (status, proposal_id))
    return get_proposal(database, user_id, proposal_id)


def dismiss(database: Path, user_id: int, proposal_id: int) -> None:
    with _db(database) as connection:
        cursor = connection.execute("UPDATE coach_proposals SET status='dismissed' "
                                    "WHERE id=? AND user_id=? AND status='pending'", (proposal_id, user_id))
        if cursor.rowcount != 1:
            raise ValueError("Proposal is not pending")
        connection.execute("UPDATE proposal_changes SET decision='rejected' WHERE proposal_id=?", (proposal_id,))


def request_revision(database: Path, user_id: int, proposal_id: int, text: str,
                     replacement: list[dict[str, Any]]) -> dict[str, Any]:
    """Store revised draft; caller supplies validated replacements from the planner."""
    if not 1 <= len(text.strip()) <= 500:
        raise ValueError("Give a short revision request")
    with _db(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        old = connection.execute("SELECT * FROM coach_proposals WHERE id=? AND user_id=?",
                                 (proposal_id, user_id)).fetchone()
        if old is None or old["status"] != "pending" or old["base_version"] != _version(connection, user_id):
            raise ValueError("Proposal is stale or no longer pending")
        facts = json.loads(old["facts_json"])
        _validate_changes(old["kind"], facts, replacement)
        new_id = _insert_proposal(connection, user_id, old["kind"], text.strip(), facts,
                                  replacement, old["base_version"])
        connection.execute("UPDATE coach_proposals SET status='superseded' WHERE id=?", (proposal_id,))
    return get_proposal(database, user_id, new_id)


def undo_last(database: Path, user_id: int) -> dict[str, Any]:
    """Restore only affected plan rows when unchanged since approval."""
    with _db(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        record = connection.execute("SELECT * FROM plan_snapshots WHERE user_id=? AND undone_at IS NULL "
                                    "ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
        if record is None:
            raise ValueError("No coach changes to undo")
        snapshot = json.loads(record["snapshot_json"])
        for start, state in snapshot.items():
            current = [_public_row(item) for item in _rows(connection, user_id, date.fromisoformat(start))]
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
                    connection.execute("DELETE FROM plan_sessions WHERE id=? AND user_id=?", (key, user_id))
                elif key not in after:
                    restored = before[key]
                    columns = ",".join(SESSION_FIELDS)
                    connection.execute(f"INSERT INTO plan_sessions({columns},created_at,updated_at) "
                                       f"VALUES({','.join('?' for _ in SESSION_FIELDS)},?,?)",
                                       (*(restored[field] for field in SESSION_FIELDS), _now(), _now()))
                else:
                    restored = before[key]
                    connection.execute("UPDATE plan_sessions SET sport=?,intent=?,duration_min=?,hr_cap_bpm=?,"
                                       "notes=?,status=?,linked_activity_id=?,updated_at=? WHERE id=? AND user_id=?",
                                       (restored["sport"], restored["intent"], restored["duration_min"],
                                        restored["hr_cap_bpm"], restored["notes"], restored["status"],
                                        restored["linked_activity_id"], _now(), key, user_id))
        connection.execute("UPDATE plan_snapshots SET undone_at=? WHERE id=?", (_now(), record["id"]))
        version = _bump(connection, user_id)
    return {"undone_snapshot_id": record["id"], "version": version}


def link_activity(connection: Any, user_id: int, activity_id: int, day: date, sport: str) -> bool:
    """Use the import transaction; never change the logged activity."""
    row = connection.execute(
        "SELECT id FROM plan_sessions WHERE user_id=? AND date=? AND sport=? AND status='planned' "
        "AND linked_activity_id IS NULL ORDER BY CASE origin WHEN 'fixed' THEN 0 ELSE 1 END,id LIMIT 1",
        (user_id, day.isoformat(), sport)).fetchone()
    if row is None:
        return False
    connection.execute("UPDATE plan_sessions SET status='done',linked_activity_id=?,updated_at=? WHERE id=?",
                       (activity_id, _now(), row[0]))
    return True
