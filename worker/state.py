"""Small transactional state store for idempotent scheduled messages."""

from __future__ import annotations

import fcntl
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path

DEFAULTS = {"morning_enabled": 1, "morning_latest": "10:00", "day_review_time": "17:00",
            "weekly_weekday": 6, "weekly_time": "18:00", "quiet_start": "22:00", "quiet_end": "05:30",
            "morning_llm": 0, "day_llm": 0, "weekly_llm": 0, "paused": 0}


@contextmanager
def connection(database: Path) -> Iterator[sqlite3.Connection]:
    db = sqlite3.connect(database, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        with db:
            yield db
    finally:
        db.close()


def preferences(database: Path, user_id: int) -> dict:
    with connection(database) as db:
        row = db.execute("SELECT * FROM notification_settings WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else {"user_id": user_id, **DEFAULTS}


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
    for field in ("morning_enabled", "morning_llm", "day_llm", "weekly_llm", "paused"):
        if merged[field] not in (0, 1, False, True):
            raise ValueError(f"Invalid {field} value")
    fields = list(DEFAULTS)
    with connection(database) as db:
        db.execute("INSERT INTO notification_settings(user_id," + ",".join(fields) + ") VALUES(" +
                   ",".join("?" for _ in range(len(fields) + 1)) + ") ON CONFLICT(user_id) DO UPDATE SET " +
                   ",".join(f"{field}=excluded.{field}" for field in fields),
                   (user_id, *(merged[field] for field in fields)))


def claim(database: Path, user_id: int, job: str, day: date, now: datetime) -> bool:
    """Claim before external delivery: uncertain sends are never repeated."""
    with connection(database) as db:
        cursor = db.execute("INSERT OR IGNORE INTO job_runs(user_id,job,run_date,status,started_at,attempts) "
                            "VALUES(?,?,?,?,?,1)", (user_id, job, day.isoformat(), "sending",
                                              now.astimezone(UTC).isoformat()))
        return cursor.rowcount == 1


def finish(database: Path, user_id: int, job: str, day: date, now: datetime,
           *, message: str | None = None, error: str | None = None) -> None:
    status = ("failed" if job.startswith("sync-") or job == "daily_backup" else "uncertain") if error else (
        "sent" if message is not None else "done")
    with connection(database) as db:
        db.execute("UPDATE job_runs SET status=?,finished_at=?,error=?,message_text=? "
                   "WHERE user_id=? AND job=? AND run_date=?",
                   (status, now.astimezone(UTC).isoformat(), error,
                    message, user_id, job, day.isoformat()))


def history(database: Path, user_id: int, limit: int = 30) -> list[dict]:
    with connection(database) as db:
        return [dict(row) for row in db.execute("SELECT job,run_date,status,started_at,finished_at,error,"
                                                "message_text FROM job_runs WHERE user_id=? "
                                                "ORDER BY started_at DESC LIMIT ?", (user_id, limit))]


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
