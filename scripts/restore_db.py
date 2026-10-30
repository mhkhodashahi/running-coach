"""Restore a SQLite backup only after confirmation and a safety backup."""

from __future__ import annotations

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path

from config import BASE_DIR, get_settings
from scripts.backup_db import backup_database
from worker.state import worker_running


def restore_database(source: Path, target: Path, backup_dir: Path, *, confirmed: bool) -> Path:
    """Return the pre-restore safety backup path; never restore while a worker runs."""
    if not confirmed:
        raise ValueError("Restore requires confirmation")
    source = source.expanduser().resolve(strict=True)
    target = target.expanduser().resolve(strict=True)
    if source == target:
        raise ValueError("Restore source and destination must differ")
    if worker_running(target):
        raise RuntimeError("Stop the worker before restoring the database")
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ValueError("Restore source failed SQLite integrity_check")
    safety = backup_database(target, backup_dir.expanduser())
    # The backup API updates the existing SQLite database without orphaning its WAL sidecars.
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
        with closing(sqlite3.connect(target)) as restored:
            original.backup(restored)
            if restored.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise RuntimeError("Restored database failed SQLite integrity_check; use the safety backup")
    return safety


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="source", required=True, type=Path)
    args = parser.parse_args()
    target = BASE_DIR / "db" / "running_coach.db"
    if worker_running(target):
        raise SystemExit("Stop the worker before restoring the database")
    if input(f"Restore {target} from {args.source}? Type RESTORE to confirm: ").strip() != "RESTORE":
        raise SystemExit("Restore cancelled; database unchanged")
    backup = restore_database(args.source, target, get_settings().backup_dir, confirmed=True)
    print(f"Restored {target}. Safety backup: {backup}")


if __name__ == "__main__":
    main()
