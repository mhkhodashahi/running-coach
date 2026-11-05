"""User-scoped timeline notes with a small, explicit write API."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from db.repositories.notes import TimelineNoteRepository
from db.session import session_scope

MAX_NOTE_LENGTH = 200


def read_notes(database: Path, user_id: int, start: date, end: date) -> tuple[dict, ...]:
    if end < start:
        return ()
    url = f"sqlite:///file:{database.resolve()}?mode=ro&uri=true"
    with session_scope(url) as session:
        return TimelineNoteRepository(session).list_between(user_id, start, end)


def save_note(database: Path, user_id: int, day: date, text: str, note_id: int | None = None) -> int:
    clean = text.strip()
    if not 1 <= len(clean) <= MAX_NOTE_LENGTH:
        raise ValueError("Note must be 1–200 characters")
    now = datetime.now(UTC).replace(tzinfo=None).isoformat()
    with session_scope(f"sqlite:///{database.resolve()}") as session:
        return TimelineNoteRepository(session).save(user_id, day, clean, datetime.fromisoformat(now), note_id)


def delete_note(database: Path, user_id: int, note_id: int) -> None:
    with session_scope(f"sqlite:///{database.resolve()}") as session:
        deleted = TimelineNoteRepository(session).delete(user_id, note_id)
        if not deleted:
            raise ValueError("Note not found")
