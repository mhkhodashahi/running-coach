"""Opt-in, idempotent extraction of coach-memory suggestions from idle chats."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from coach.agent import CoachAgent
from config import Settings
from db.repositories.coach_memory_extraction import CoachMemoryExtractionRepository
from db.session import session_scope
from llm.factory import get_llm_client
from services.coach_memory_service import extract_suggestions
from worker.state import preferences


def suggest_from_idle_chat(settings: Settings, now: datetime, *, client=None) -> int:
    """Process each chat batch once after five idle minutes, respecting privacy and call limits."""
    if settings.llm_provider in {"openai", "chatgpt"} and not (
            settings.allow_remote_llm and settings.remote_athlete_data_approved):
        return 0
    if settings.llm_provider not in {"openai", "chatgpt", "ollama"}:
        return 0
    user_id = settings.default_user_id
    if not preferences(settings.db_path, user_id).get("suggest_memories_llm"):
        return 0
    utc_now = now.astimezone(UTC).replace(tzinfo=None) if now.tzinfo else now
    with session_scope(settings.db_url) as session:
        cursor, rows = CoachMemoryExtractionRepository(session).next_batch(user_id)
    latest_value = rows[-1]["created_at"] if rows else None
    latest = (latest_value if isinstance(latest_value, datetime) else
              datetime.fromisoformat(str(latest_value)) if latest_value else utc_now)
    ready = rows if rows and utc_now - latest.replace(tzinfo=None) >= timedelta(minutes=5) else []
    if not ready:
        return 0
    client = client or get_llm_client(settings.llm_provider, settings.openai_api_key, settings.openai_model,
                                      settings.ollama_base_url, settings.ollama_model)
    try:
        CoachAgent(settings, client, user_id)._count_request()
    except RuntimeError:
        return 0
    turns = [{"role": role, "text": message} for row in ready for role, message in
             (("athlete", row["question"]), ("coach", row["answer"]))]
    try:
        count = extract_suggestions(settings.db_path, user_id, turns, client)
    except Exception:
        return 0
    last_id = int(ready[-1]["id"])
    with session_scope(settings.db_url) as session:
        CoachMemoryExtractionRepository(session).advance(user_id, last_id, utc_now)
    return count
