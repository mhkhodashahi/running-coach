"""Inbound Telegram chat loop for Marathon Coach."""

from __future__ import annotations

import time
from dataclasses import dataclass

from config import Settings, get_settings
from services.telegram_service import TelegramService
from services.training_chat_service import TrainingChatService


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
            reply = "This Marathon Coach bot is private. Your chat id is not authorized."
            self.telegram_service.send_text(reply, recipient=chat_id)
            return TelegramHandleResult(handled=True, reply=reply, authorized=False)

        reply = self._reply_for_text(text)
        self.telegram_service.send_text(reply, recipient=chat_id)
        return TelegramHandleResult(handled=True, reply=reply)

    def run_polling(self, poll_timeout: int = 30, idle_sleep_seconds: float = 1.0) -> None:
        """Run a local long-polling loop until interrupted."""

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
                "Marathon Coach chat is ready.\n\n"
                "Ask questions like:\n"
                "- How is my recovery today?\n"
                "- What was my weekly mileage?\n"
                "- Am I on track for my marathon goal?\n"
                "- What should I do tomorrow?"
            )
        if command == "/status":
            return self.chat_service.answer("Give me a concise current training status.").text
        return self.chat_service.answer(text).text
