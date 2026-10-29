"""Pure, secret-free Me page presentation."""

from __future__ import annotations

from typing import Any


def me_view(context: dict[str, Any], *, telegram_configured: bool,
            garmin_configured: bool, public_link_configured: bool,
            version: str, source_url: str) -> dict[str, Any]:
    """Expose booleans for credentials; never pass their values to a template."""
    return {"title": "Me", "version": version, "source_url": source_url,
            "telegram_status": "Set" if telegram_configured else "Not set",
            "garmin_status": "Set" if garmin_configured else "Not set",
            "public_link_status": "Set" if public_link_configured else "Not set",
            "provider_location": "Remote" if context["provider"] in ("openai", "chatgpt") else "Local",
            "env_settings": (("Heart-rate zones", "Set in .env"),
                             ("Sleep goal", "Set in .env"),
                             ("Coach provider", "Set in .env"),
                             ("Remote sharing", "Set in .env")),
            "notifications": context["messages"]}
