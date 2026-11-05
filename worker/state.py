"""Small transactional state store for idempotent scheduled messages."""

from __future__ import annotations

import fcntl
import re
from datetime import UTC, date, datetime
from pathlib import Path

from db.repositories.worker_state import WorkerStateRepository
from db.session import session_scope

DEFAULTS = {"morning_enabled": 1, "morning_latest": "10:00", "day_review_time": "17:00",
            "weekly_weekday": 6, "weekly_time": "18:00", "quiet_start": "22:00", "quiet_end": "05:30",
            "morning_llm": 0, "day_llm": 0, "weekly_llm": 0, "suggest_memories_llm": 0, "paused": 0}


def _database_url(database: Path) -> str:
    return f"sqlite:///{database.resolve()}"


def preferences(database: Path, user_id: int) -> dict:
    with session_scope(_database_url(database)) as session:
        values = WorkerStateRepository(session).preferences(user_id)
    return values if values is not None else {"user_id": user_id, **DEFAULTS}


def save_preferences(database: Path, user_id: int, values: dict) -> None:
    allowed = set(DEFAULTS)
    if set(values) - allowed:
        raise ValueError("Unknown notification setting")
    merged = preferences(database, user_id) | values
    for field in ("morning_latest", "day_review_time", "weekly_time", "quiet_start", "quiet_end"):
        raw = str(merged[field])
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", raw):
            raise ValueError(f"Invalid {field} time")
    if int(merged["weekly_weekday"]) not in range(7):
        raise ValueError("Invalid weekly review day")
    for field in ("morning_enabled", "morning_llm", "day_llm", "weekly_llm", "suggest_memories_llm", "paused"):
        if merged[field] not in (0, 1, False, True):
            raise ValueError(f"Invalid {field} value")
    fields = list(DEFAULTS)
    with session_scope(_database_url(database)) as session:
        WorkerStateRepository(session).save_preferences(user_id, fields, merged)


def claim(database: Path, user_id: int, job: str, day: date, now: datetime) -> bool:
    """Claim before external delivery: uncertain sends are never repeated."""
    with session_scope(_database_url(database)) as session:
        return WorkerStateRepository(session).claim(user_id, job, day, now.astimezone(UTC))


def finish(database: Path, user_id: int, job: str, day: date, now: datetime,
           *, message: str | None = None, error: str | None = None) -> None:
    status = ("failed" if job.startswith("sync-") or job == "daily_backup" else "uncertain") if error else (
        "sent" if message is not None else "done")
    with session_scope(_database_url(database)) as session:
        WorkerStateRepository(session).finish(user_id, job, day, now.astimezone(UTC), status, message, error)


def history(database: Path, user_id: int, limit: int = 30) -> list[dict]:
    with session_scope(_database_url(database)) as session:
        return WorkerStateRepository(session).history(user_id, limit)


def in_quiet_hours(now: datetime, start: str, end: str) -> bool:
    clock = now.strftime("%H:%M")
    if start == end:
        return False
    return start <= clock < end if start < end else clock >= start or clock < end


def worker_running(database: Path) -> bool:
    path = database.with_suffix(".worker.lock")
    if not path.exists():
        return False
    with path.open("r") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return False
