"""Upgrade a SQLite database, automatically backing it up before any changes."""

import argparse
from pathlib import Path

from db.migration_runner import upgrade_database


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="Exact SQLite path; no legacy filename redirection")
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args()
    backup = upgrade_database(args.db, args.backup_dir)
    if backup:
        print(f"Pre-upgrade backup: {backup}")
    print(f"Database at migration head: {args.db.resolve()}")


if __name__ == "__main__":
    main()
