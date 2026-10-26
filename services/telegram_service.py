"""Outbound Telegram delivery."""

from __future__ import annotations

import time

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

    def redact(self, value: str) -> str:
        token = self.settings.telegram_bot_token
        return value.replace(token, "[redacted bot token]") if token else value

    def _request(self, method: str, endpoint: str, **kwargs) -> dict:
        url = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/{endpoint}"
        for attempt in range(3):
            try:
                response = requests.post(url, **kwargs) if method == "POST" else requests.get(url, **kwargs)
                if getattr(response, "status_code", None) == 429 and attempt < 2:
                    delay = getattr(response, "headers", {}).get("Retry-After", 2 ** attempt)
                    time.sleep(min(30, max(1, int(delay))))
                    continue
                response.raise_for_status()
                payload = response.json()
                break
            except Exception as exc:
                raise RuntimeError(self.redact(str(exc))) from None
        if not payload.get("ok"):
            raise RuntimeError(self.redact(str(payload)))
        return payload

    def send_proposal_prompt(self, text: str, proposal_id: int) -> None:
        if not self.configured:
            raise ValueError("Telegram settings are incomplete.")
        buttons = [[{"text": "Apply all", "callback_data": f"proposal:{proposal_id}:apply"},
                    {"text": "Dismiss", "callback_data": f"proposal:{proposal_id}:dismiss"}],
                   [{"text": "Review in app", "callback_data": f"proposal:{proposal_id}:review"}]]
        self._request("POST", "sendMessage", json={"chat_id": self.settings.telegram_chat_id,
                      "text": text, "reply_markup": {"inline_keyboard": buttons}}, timeout=30)

    def send(self, title: str, body: str, recipient: str | None = None) -> tuple[str, str]:
        chat_id = (recipient or self.settings.telegram_chat_id).strip()
        if not chat_id:
            raise ValueError("TELEGRAM_CHAT_ID is not configured.")
        if not self.configured:
            raise ValueError("Telegram settings are incomplete. Configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")

        text = f"{title.strip()}\n\n{body.strip()}".strip()
        self._request("POST", "sendMessage", json={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
            }, timeout=30)
        return "sent", f"Sent to Telegram chat {chat_id}"

    def send_text(self, text: str, recipient: str | None = None) -> tuple[str, str]:
        """Send raw text to a Telegram chat."""

        chat_id = (recipient or self.settings.telegram_chat_id).strip()
        if not chat_id:
            raise ValueError("TELEGRAM_CHAT_ID is not configured.")
        if not self.configured:
            raise ValueError("Telegram settings are incomplete. Configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")

        self._request("POST", "sendMessage", json={
                "chat_id": chat_id,
                "text": text.strip(),
                "disable_web_page_preview": True,
            }, timeout=30)
        return "sent", f"Sent to Telegram chat {chat_id}"

    def send_rating_prompt(self, text: str, activity_id: int) -> None:
        if not self.configured:
            raise ValueError("Telegram settings are incomplete.")
        buttons = [[{"text": str(value), "callback_data": f"rpe:{activity_id}:{value}"}
                    for value in range(start, min(start + 6, 11))] for start in (0, 6)]
        self._request("POST", "sendMessage", json={"chat_id": self.settings.telegram_chat_id,
                      "text": text, "reply_markup": {"inline_keyboard": buttons}}, timeout=30)

    def acknowledge_callback(self, callback_id: str, text: str) -> None:
        self._request("POST", "answerCallbackQuery", json={"callback_query_id": callback_id,
                      "text": text}, timeout=30)

    def get_updates(self, offset: int | None = None, timeout: int = 30) -> list[dict]:
        """Fetch inbound Telegram updates using long polling."""

        if not self.settings.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not configured.")
        params: dict[str, int | str] = {
            "timeout": int(timeout),
            "allowed_updates": '["message","callback_query"]',
        }
        if offset is not None:
            params["offset"] = int(offset)
        payload = self._request("GET", "getUpdates", params=params, timeout=timeout + 10)
        return list(payload.get("result") or [])
