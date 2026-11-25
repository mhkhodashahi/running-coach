"""Upgrade a SQLite database, automatically backing it up before any changes."""

import argparse
from pathlib import Path

from db.migration_runner import upgrade_database


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="Exact SQLite path; no legacy filename redirection")
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--ensure-user", action="store_true",
                        help="Create the configured default profile if missing; never edit an existing profile")
    args = parser.parse_args()
    backup = upgrade_database(args.db, args.backup_dir)
    if backup:
        print(f"Pre-upgrade backup: {backup}")
    if args.ensure_user:
        from config import get_settings
        from db.models import User
        from db.repositories.compatibility import get_or_create_default_user
        from db.session import session_scope

        user_id = get_settings().default_user_id
        with session_scope(f"sqlite:///{args.db.resolve()}") as session:
            if session.get(User, user_id) is None:
                get_or_create_default_user(session, user_id)
    print(f"Database at migration head: {args.db.resolve()}")


if __name__ == "__main__":
    main()
