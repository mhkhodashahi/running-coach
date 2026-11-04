"""Explicit updates for saved, athlete-approved planned workouts."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from coach.proposals import _bump, _db, create_proposal, get_week, monday


def read_session(database: Path, user_id: int, session_id: int) -> dict[str, Any]:
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM plan_sessions WHERE id=? AND user_id=?",
                         (session_id, user_id)).fetchone()
    if row is None:
        raise ValueError("Planned session not found")
    return dict(row)


def use_shorter_variant(database: Path, user_id: int, session_id: int) -> dict[str, Any]:
    with _db(database) as db:
        row = db.execute("SELECT * FROM plan_sessions WHERE id=? AND user_id=?",
                         (session_id, user_id)).fetchone()
        if row is None or row["status"] != "planned":
            raise ValueError("Only a planned session can switch to its shorter version")
        if not row["workout_json"]:
            raise ValueError("This session has no stored workout variants")
        workout = json.loads(row["workout_json"])
        variant = (workout.get("variants") or {}).get("shorter")
        if not variant:
            raise ValueError("No shorter version is available")
        workout["steps"] = variant["steps"]
        workout["duration_min"] = variant["duration_min"]
        workout["title"] = f"{workout.get('title', row['sport'].title()).rsplit(' ', 1)[0]} {variant['duration_min']} min"
        db.execute("UPDATE plan_sessions SET duration_min=?,workout_json=?,updated_at=CURRENT_TIMESTAMP "
                   "WHERE id=? AND user_id=?",
                   (variant["duration_min"], json.dumps(workout), session_id, user_id))
        _bump(db, user_id)
    return read_session(database, user_id, session_id)


def propose_move(database: Path, user_id: int, session_id: int, target: date) -> dict[str, Any]:
    row = read_session(database, user_id, session_id)
    source = date.fromisoformat(row["date"])
    if row["status"] != "planned" or row["origin"] in {"fixed", "protected"}:
        raise ValueError("Only a flexible planned session can be moved")
    if target == source:
        raise ValueError("Choose a different day")
    current_week = get_week(database, user_id, monday(source))
    facts = [
        {"id": "SESSION_DAY", "metric": "Current session date", "display": source.isoformat(),
         "source": "plan_sessions.date"},
        {"id": "REQUESTED_DAY", "metric": "Requested session date", "display": target.isoformat(),
         "source": "athlete request"},
    ]
    workout = json.loads(row["workout_json"]) if row["workout_json"] else None
    session = {key: row[key] for key in
               ("id", "sport", "intent", "duration_min", "hr_cap_bpm", "notes", "status",
                "workout_type")}
    session.update(date=target.isoformat(), workout=workout)
    previous = {**session, "date": source.isoformat()}
    group_id = f"move-session-{session_id}"
    return create_proposal(database, user_id, "change", "Move this workout", facts, [
        {"change_type": "remove", "session": previous, "reason": "Remove the workout from its current day.",
         "fact_ids": ["SESSION_DAY"], "group_id": group_id},
        {"change_type": "add", "session": session, "reason": "Place the workout on the requested day.",
         "fact_ids": ["REQUESTED_DAY"], "group_id": group_id},
    ], base_version=current_week["version"])
