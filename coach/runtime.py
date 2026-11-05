"""Shared runtime safeguards for coach jobs and agent requests."""

from __future__ import annotations

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from db.migration_runner import database_is_current


def require_current_database(database: Path) -> None:
    if not database_is_current(database):
        raise RuntimeError(
            f"Database needs an upgrade. Stop all jobs, then run:\n"
            f"python -m scripts.upgrade_db --db {database}"
        )


@contextmanager
def user_job_lock(database: Path, user_id: int) -> Iterator[None]:
    """Prevent concurrent LLM jobs for the same user and database."""
    lock_path = database.with_name(f".{database.name}.coach-{user_id}.lock")
    with lock_path.open("a+b") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("A coach job is already running for this user. Try again shortly.") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
