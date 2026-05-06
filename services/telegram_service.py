"""Outbound Telegram delivery."""

from __future__ import annotations

import requests

from config import Settings


class TelegramService:
    """Send coaching digests through the Telegram Bot API."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.telegram_bot_token and self.settings.telegram_chat_id)

    def default_recipient(self) -> str:
        return self.settings.telegram_chat_id

    def send(self, title: str, body: str, recipient: str | None = None) -> tuple[str, str]:
        chat_id = (recipient or self.settings.telegram_chat_id).strip()
        if not chat_id:
            raise ValueError("TELEGRAM_CHAT_ID is not configured.")
        if not self.configured:
            raise ValueError("Telegram settings are incomplete. Configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")

        text = f"{title.strip()}\n\n{body.strip()}".strip()
        response = requests.post(
            f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(str(payload))
        return "sent", f"Sent to Telegram chat {chat_id}"

    def send_text(self, text: str, recipient: str | None = None) -> tuple[str, str]:
        """Send raw text to a Telegram chat."""

        chat_id = (recipient or self.settings.telegram_chat_id).strip()
        if not chat_id:
            raise ValueError("TELEGRAM_CHAT_ID is not configured.")
        if not self.configured:
            raise ValueError("Telegram settings are incomplete. Configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")

        response = requests.post(
            f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text.strip(),
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(str(payload))
        return "sent", f"Sent to Telegram chat {chat_id}"

    def get_updates(self, offset: int | None = None, timeout: int = 30) -> list[dict]:
        """Fetch inbound Telegram updates using long polling."""

        if not self.settings.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not configured.")
        params: dict[str, int | str] = {
            "timeout": int(timeout),
            "allowed_updates": '["message"]',
        }
        if offset is not None:
            params["offset"] = int(offset)
        response = requests.get(
            f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/getUpdates",
            params=params,
            timeout=timeout + 10,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(str(payload))
        return list(payload.get("result") or [])
