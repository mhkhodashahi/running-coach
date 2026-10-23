"""Inbound Telegram chat loop for Running Coach."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from coach.plan import WEEKDAYS, monday
from config import Settings, get_settings
from db.setup import init_db
from services.daily_decision_service import get_or_create_daily_decision
from services.telegram_service import TelegramService
from services.training_chat_service import TrainingChatService
from services.weekly_plan_service import (
    accept_change,
    get_weekly_plan,
    list_proposals,
    propose_week,
    reject_change,
    revise_proposal,
    set_fixed_commitment,
    undo_last_coach_change,
)


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
                "\n\nPlan: /plan [MONDAY], /plan-suggest [MONDAY], /plan-accept ID, /plan-reject ID, "
                "/plan-revise ID make Saturday a rest day, /plan-undo. "
                "Fixed team training: /plan-fixed Saturday football; /plan-unfix Saturday. "
                "A YYYY-MM-DD date also works for fixed training."
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
        today = datetime.now(ZoneInfo(self.settings.local_timezone)).date()
        start = monday(today)
        try:
            if command in {"/plan", "/plan-suggest", "/plan-undo"} and len(parts) >= 2:
                selected = date.fromisoformat(parts[1])
                if selected != monday(selected):
                    return "Choose a Monday date in YYYY-MM-DD format."
                start = selected
            if command == "/plan":
                plan = get_weekly_plan(start, settings=self.settings)
                lines = [f"Week of {start.isoformat()} (revision {plan['revision']}):"]
                for offset in range(7):
                    day = start + timedelta(days=offset)
                    session = plan["sessions"].get(day.isoformat())
                    lines.append(f"{day:%a}: {session['sport']} {session['intent']} "
                                 f"({session['duration_min']} min){' fixed' if session['fixed'] else ''}"
                                 if session else f"{day:%a}: rest / open")
                for proposal in list_proposals(start, settings=self.settings)[:3]:
                    pending = [change for change in proposal["changes"] if change["status"] == "pending"]
                    lines.append(f"Proposal {proposal['id']}: {proposal['status']}; "
                                 f"pending changes {', '.join(str(change['id']) for change in pending) or 'none'}")
                    evidence = {fact["id"]: fact["display"] for fact in proposal["facts"]}
                    for change in pending:
                        session = change["session"]
                        label = (f"{session['sport']} {session['intent']} ({session['duration_min']} min)"
                                 if session else "rest")
                        cited = ", ".join(evidence[fact_id] for fact_id in change["fact_ids"])
                        lines.append(f"  {change['id']} {change['day']}: {label}. {change['reason']} [{cited}]")
                return "\n".join(lines)[:3900]
            if command == "/plan-suggest":
                proposal = propose_week(start, settings=self.settings, today=today)
                ids = ", ".join(str(change["id"]) for change in proposal["changes"])
                return f"Proposal {proposal['id']} created. Review /plan; accept or reject each change ID: {ids}."
            if command == "/plan-undo":
                undo_last_coach_change(start, settings=self.settings)
                return "Last coach change undone. Review /plan."
            if command in {"/plan-accept", "/plan-reject"}:
                if len(parts) < 2 or not parts[1].isdigit():
                    return f"Use {command} CHANGE_ID."
                change_id = int(parts[1])
                if command == "/plan-accept":
                    accept_change(change_id, settings=self.settings)
                    return f"Change {change_id} accepted. Review /plan."
                reject_change(change_id, settings=self.settings)
                return f"Change {change_id} rejected. Review /plan."
            if command == "/plan-revise":
                if len(parts) < 3 or not parts[1].isdigit():
                    return "Use /plan-revise PROPOSAL_ID make Saturday a rest day."
                proposal = revise_proposal(int(parts[1]), parts[2], settings=self.settings)
                return f"Revision proposed as {proposal['id']}; no change applied. Review /plan."
            if command in {"/plan-fixed", "/plan-unfix"}:
                if len(parts) < 2:
                    return f"Use {command} WEEKDAY-or-YYYY-MM-DD" + (
                        " SPORT." if command == "/plan-fixed" else ".")
                day = (start + timedelta(days=WEEKDAYS.index(parts[1].lower()))
                       if parts[1].lower() in WEEKDAYS else date.fromisoformat(parts[1]))
                if command == "/plan-fixed":
                    if len(parts) < 3 or parts[2].lower() not in {"football", "volleyball"}:
                        return "Use /plan-fixed WEEKDAY football|volleyball."
                    set_fixed_commitment(day, parts[2].lower(), settings=self.settings)
                    return f"Fixed {parts[2].lower()} training saved for {day:%A}. Review /plan."
                set_fixed_commitment(day, None, settings=self.settings)
                return f"Fixed team training removed from {day:%A}. Review /plan."
            return "Unknown plan command. Send /help for plan commands."
        except (ValueError, sqlite3.Error) as exc:
            return str(exc)
