"""User-scoped timeline notes with a small, explicit write API."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

MAX_NOTE_LENGTH = 200


def read_notes(database: Path, user_id: int, start: date, end: date) -> tuple[dict, ...]:
    if end < start:
        return ()
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT id,date,text FROM timeline_notes WHERE user_id=? AND date BETWEEN ? AND ? "
            "ORDER BY date,id LIMIT 500", (user_id, start.isoformat(), end.isoformat())).fetchall()
    return tuple(dict(row) for row in rows)


def save_note(database: Path, user_id: int, day: date, text: str, note_id: int | None = None) -> int:
    clean = text.strip()
    if not 1 <= len(clean) <= MAX_NOTE_LENGTH:
        raise ValueError("Note must be 1–200 characters")
    now = datetime.now(UTC).replace(tzinfo=None).isoformat()
    with sqlite3.connect(database) as connection:
        if note_id is None:
            cursor = connection.execute(
                "INSERT INTO timeline_notes(user_id,date,text,created_at,updated_at) VALUES(?,?,?,?,?)",
                (user_id, day.isoformat(), clean, now, now))
            return cursor.lastrowid
        cursor = connection.execute(
            "UPDATE timeline_notes SET date=?,text=?,updated_at=? WHERE id=? AND user_id=?",
            (day.isoformat(), clean, now, note_id, user_id))
        if cursor.rowcount != 1:
            raise ValueError("Note not found")
        return note_id


def delete_note(database: Path, user_id: int, note_id: int) -> None:
    with sqlite3.connect(database) as connection:
        cursor = connection.execute("DELETE FROM timeline_notes WHERE id=? AND user_id=?", (note_id, user_id))
        if cursor.rowcount != 1:
            raise ValueError("Note not found")
