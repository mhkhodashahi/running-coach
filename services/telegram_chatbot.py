"""Inbound Telegram chat loop for Running Coach."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from coach.proposals import list_proposals, monday
from config import Settings, get_settings
from db.setup import init_db
from services.daily_decision_service import get_or_create_daily_decision
from services.telegram_service import TelegramService
from services.training_chat_service import TrainingChatService
from services.weekly_plan_service import get_weekly_plan


@dataclass(frozen=True)
class TelegramHandleResult:
    """Result of processing one inbound Telegram message."""

    handled: bool
    reply: str | None = None
    authorized: bool = True


class TelegramTrainingChatBot:
    """Authorize Telegram messages, answer with training context, and send replies."""

    def __init__(
        self,
        settings: Settings | None = None,
        telegram_service: TelegramService | None = None,
        chat_service: TrainingChatService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.telegram_service = telegram_service or TelegramService(self.settings)
        self.chat_service = chat_service or TrainingChatService(self.settings)

    def handle_update(self, update: dict) -> TelegramHandleResult:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id") or "").strip()
        text = str(message.get("text") or "").strip()
        if not chat_id or not text:
            return TelegramHandleResult(handled=False)

        if not self._authorized(chat_id):
            reply = "This Running Coach bot is private. Your chat id is not authorized."
            self.telegram_service.send_text(reply, recipient=chat_id)
            return TelegramHandleResult(handled=True, reply=reply, authorized=False)

        reply = self._reply_for_text(text)
        self.telegram_service.send_text(reply, recipient=chat_id)
        return TelegramHandleResult(handled=True, reply=reply)

    def run_polling(self, poll_timeout: int = 30, idle_sleep_seconds: float = 1.0) -> None:
        """Run a local long-polling loop until interrupted."""

        init_db()
        if not self.settings.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not configured.")
        if not self.settings.telegram_chat_id:
            raise ValueError("TELEGRAM_CHAT_ID is not configured.")

        offset: int | None = None
        while True:
            updates = self.telegram_service.get_updates(offset=offset, timeout=poll_timeout)
            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    offset = update_id + 1
                self.handle_update(update)
            if not updates:
                time.sleep(idle_sleep_seconds)

    def _authorized(self, chat_id: str) -> bool:
        return chat_id == str(self.settings.telegram_chat_id).strip()

    def _reply_for_text(self, text: str) -> str:
        command = text.split()[0].lower()
        if command in {"/start", "/help"}:
            return (
                "Running Coach chat is ready.\n\n"
                "Ask questions like:\n"
                "- How is my recovery today?\n"
                "- What was my weekly mileage?\n"
                "- Am I on track for my running goal?\n"
                "- What should I do tomorrow?"
                "\n\nPlan: /plan [MONDAY] shows the week and pending proposals. "
                "Review and apply changes in the app."
            )
        if command.startswith("/plan"):
            return self._plan_command(text)
        if command == "/status":
            return self.chat_service.answer("Give me a concise current training status.").text
        if command == "/today":
            day = datetime.now(ZoneInfo(self.settings.local_timezone)).date()
            decision = get_or_create_daily_decision(day, settings=self.settings)
            lines = [f"{decision.headline} {decision.explanation}"]
            if decision.provisional:
                lines.append(f"Provisional: based on {decision.based_on}; last sync {decision.last_sync_time}.")
            for item in decision.sports:
                lines.append(f"{item['rank']}. {item['sport']}: {item['session']['intent']} "
                             f"({item['session']['duration_min']} min). {item['reason']}.")
            if decision.optional:
                lines.append(decision.optional)
            for option in decision.team_options:
                lines.append(f"{option['sport'].title()}: {option['label']}.")
            if decision.athlete_choice:
                lines.append(f"Your choice: {decision.athlete_choice} (coach: {decision.intensity}).")
            return "\n".join(lines)
        return self.chat_service.answer(text).text

    def _plan_command(self, text: str) -> str:
        parts = text.split(maxsplit=2)
        command = parts[0].lower()
        start = monday(datetime.now(ZoneInfo(self.settings.local_timezone)).date())
        try:
            if command == "/plan" and len(parts) >= 2:
                selected = date.fromisoformat(parts[1])
                if selected != monday(selected):
                    return "Choose a Monday date in YYYY-MM-DD format."
                start = selected
            if command == "/plan":
                plan = get_weekly_plan(start, settings=self.settings)
                lines = [f"Week of {start.isoformat()} (version {plan['version']}):"]
                for offset in range(7):
                    day = start + timedelta(days=offset)
                    sessions = [item for item in plan["sessions"] if item["date"] == day.isoformat()]
                    lines.append(f"{day:%a}: " + (", ".join(
                        f"{item['sport']} {item['intent']} ({item['duration_min']} min)"
                        f"{' fixed' if item['origin'] == 'fixed' else ''}" for item in sessions) or "rest / open"))
                for proposal in list_proposals(self.settings.db_path, self.settings.default_user_id, start)[:3]:
                    pending = [change for change in proposal["changes"] if change["decision"] == "pending"]
                    lines.append(f"Proposal {proposal['id']}: {proposal['status']}; "
                                 f"{len(pending)} pending. Review it in the app.")
                return "\n".join(lines)[:3900]
            return "Plan changes need individual approval in the app. Use /plan to review."
        except (ValueError, sqlite3.Error) as exc:
            return str(exc)
