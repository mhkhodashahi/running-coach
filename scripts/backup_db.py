"""Create a consistent, timestamped SQLite backup (including committed WAL data)."""

from __future__ import annotations

import argparse
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path


def backup_database(database: Path, backup_dir: Path | None = None) -> Path:
    database = database.expanduser().resolve(strict=True)
    directory = backup_dir or database.parent / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    # Exclusive creation avoids collisions and keeps private backups owner-readable only.
    with tempfile.NamedTemporaryFile(prefix=f"{database.stem}.{stamp}.", suffix=".db", dir=directory, delete=False) as file:
        destination = Path(file.name)
    try:
        with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(destination)) as target:
                source.backup(target)
                if target.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise RuntimeError("Backup failed SQLite integrity_check")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="Exact SQLite path; no legacy filename redirection")
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args()
    print(backup_database(args.db, args.backup_dir))


if __name__ == "__main__":
    main()
