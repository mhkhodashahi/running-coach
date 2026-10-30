"""Dated online SQLite backups kept outside the source tree."""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import date
from pathlib import Path

NAME = re.compile(r"^pulse\.(daily|weekly)\.(\d{4}-\d{2}-\d{2})\.db$")


def latest_backup(directory: Path) -> Path | None:
    matches = [path for path in directory.glob("pulse.daily.*.db") if path.is_file() and
               not path.is_symlink() and NAME.fullmatch(path.name)] if directory.exists() else []
    return max(matches, key=lambda path: path.name, default=None)


def prune_backups(directory: Path) -> tuple[Path, ...]:
    """Delete only dated backup files of this worker, never other files or symlinks."""
    removed: list[Path] = []
    for kind, keep in (("daily", 14), ("weekly", 8)):
        matching = sorted((path for path in directory.iterdir() if path.is_file() and
                           not path.is_symlink() and (match := NAME.fullmatch(path.name)) and
                           match.group(1) == kind), key=lambda path: path.name, reverse=True)
        for path in matching[keep:]:
            path.unlink()
            removed.append(path)
    return tuple(removed)


def daily_backup(database: Path, directory: Path, day: date, repo_root: Path) -> Path:
    """Back up the committed database, validate it, then prune owned files."""
    directory = directory.expanduser().resolve()
    root = repo_root.resolve()
    if directory == root or root in directory.parents:
        raise ValueError("Backup folder must be outside the repository")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = directory / f"pulse.daily.{day.isoformat()}.db"
    with tempfile.NamedTemporaryFile(dir=directory, prefix=".pulse-backup-", suffix=".db", delete=False) as file:
        temporary = Path(file.name)
    try:
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(temporary)) as target:
                source.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    raise RuntimeError("Backup failed SQLite integrity_check")
        temporary.replace(destination)
        if day.weekday() == 6:
            weekly = directory / f"pulse.weekly.{day.isoformat()}.db"
            shutil.copyfile(destination, weekly)
            os.chmod(weekly, 0o600)
        prune_backups(directory)
        return destination
    finally:
        temporary.unlink(missing_ok=True)
