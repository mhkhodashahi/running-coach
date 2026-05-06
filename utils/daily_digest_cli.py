"""CLI entrypoint for daily Garmin sync and coaching digest generation."""

from __future__ import annotations

import argparse

from config import get_settings
from db import repository
from db.session import session_scope
from db.setup import init_db
from services.coaching_workflow import CoachingWorkflowService
from services.import_service import GarminImportService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a goal-aware coaching digest.")
    parser.add_argument("--user-id", type=int, help="User id to coach. Defaults to DEFAULT_USER_ID.")
    parser.add_argument("--decision-type", choices=["daily", "weekly"], default="daily")
    parser.add_argument("--athlete-note", default="", help="Optional note to include in coaching context.")
    parser.add_argument("--days", type=int, default=1, help="Activity sync window in days.")
    parser.add_argument("--health-days", type=int, default=1, help="Health sync window in days.")
    parser.add_argument("--skip-sync", action="store_true", help="Skip Garmin sync and use the local database only.")
    parser.add_argument("--send-telegram", action="store_true", help="Send the generated digest through Telegram.")
    parser.add_argument("--recipient", default="", help="Override the default Telegram chat id.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings = get_settings()
    init_db()

    with session_scope() as session:
        user = repository.get_or_create_default_user(session, args.user_id or settings.default_user_id)
        repository.get_or_create_default_goal(session, user)
        if not args.skip_sync:
            GarminImportService().sync_garmin(
                session=session,
                user_id=user.id,
                days=args.days,
                health_days=args.health_days,
            )
        decision = CoachingWorkflowService().generate(
            session=session,
            user=user,
            decision_type=args.decision_type,
            athlete_note=args.athlete_note,
            send_message=bool(args.send_telegram),
            recipient=args.recipient or None,
        )

    print(decision.get("message_title", decision["email_subject"]))
    print(decision["summary"])
    print(f"Telegram status: {decision.get('message_status') or 'not_sent'}")


if __name__ == "__main__":
    main()
