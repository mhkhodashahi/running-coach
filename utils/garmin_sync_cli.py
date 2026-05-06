"""CLI entrypoint for scheduled Garmin sync jobs."""

from __future__ import annotations

import argparse

from config import get_settings
from db import repository
from db.session import session_scope
from db.setup import init_db
from services.import_service import GarminImportService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync Garmin data into the local database.")
    parser.add_argument("--user-id", type=int, help="User id to sync into. Defaults to DEFAULT_USER_ID.")
    parser.add_argument("--days", type=int, default=1, help="Activity sync window in days.")
    parser.add_argument("--health-days", type=int, default=1, help="Health sync window in days.")
    parser.add_argument(
        "--health-only",
        action="store_true",
        help="Only write health metrics to the database.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    settings = get_settings()
    init_db()

    with session_scope() as session:
        user = repository.get_or_create_default_user(
            session,
            args.user_id or settings.default_user_id,
        )
        summary = GarminImportService().sync_garmin(
            session=session,
            user_id=user.id,
            days=args.days,
            health_days=args.health_days,
            include_activities=not args.health_only,
            include_health=True,
        )

    mode = "health-only sync" if args.health_only else "full sync"
    print(
        f"Completed Garmin {mode}: "
        f"{summary.activities_imported} activities imported, "
        f"{summary.track_points_imported} GPS points imported, "
        f"{summary.laps_imported} laps imported, "
        f"{summary.health_rows_imported} health rows imported."
    )


if __name__ == "__main__":
    main()
