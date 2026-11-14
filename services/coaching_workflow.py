"""Compatibility entry point backed by the current decision and brief workflows."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from config import Settings, get_settings
from services.review_service import morning_payload, weekly_payload
from services.telegram_service import TelegramService


class CoachingWorkflowService:
    """Reuse guarded daily/weekly workflows instead of a separate model decision."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def generate(self, session: Any, user: Any, *, decision_type: str = "daily",
                 athlete_note: str = "", send_message: bool = False,
                 recipient: str | None = None) -> dict[str, Any]:
        if decision_type not in {"daily", "weekly"}:
            raise ValueError("Choose a daily or weekly digest")
        if athlete_note.strip():
            raise ValueError("Use Coach chat or a timeline note for athlete notes; the digest uses stored facts")
        settings = replace(self.settings, default_user_id=user.id)
        if session is not None and session.get_bind().url.database != str(settings.db_path):
            raise ValueError("Digest session and configured database must match")
        day = datetime.now(ZoneInfo(settings.local_timezone)).date()
        payload = (morning_payload(settings, day, use_llm=True) if decision_type == "daily" else
                   weekly_payload(settings, day, use_llm=True))
        status = "not_sent"
        if send_message:
            if recipient and recipient != settings.telegram_chat_id:
                raise ValueError("Use the configured Telegram recipient")
            TelegramService(settings).send_message(payload.html, payload.keyboard, payload.plain)
            status = "sent"
        title = payload.plain.splitlines()[0]
        return {"summary": title, "message_title": title, "message_body": payload.plain,
                "email_subject": title, "email_body": payload.plain,
                "message_status": status, "email_status": status}
