"""Opt-in, idempotent extraction of coach-memory suggestions from idle chats."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from coach.agent import CoachAgent
from config import Settings
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
    with sqlite3.connect(settings.db_path) as db:
        state = db.execute("SELECT processed_through_id FROM coach_memory_extraction_state WHERE user_id=?",
                           (user_id,)).fetchone()
        cursor = int(state[0]) if state else 0
        rows = db.execute("SELECT id,question,answer,created_at FROM coach_chat_turns WHERE user_id=? AND id>? "
                          "ORDER BY id LIMIT 20", (user_id, cursor)).fetchall()
        utc_now = now.astimezone(UTC).replace(tzinfo=None) if now.tzinfo else now
        latest = datetime.fromisoformat(rows[-1][3]) if rows else utc_now
        ready = rows if rows and utc_now - latest.replace(tzinfo=None) >= timedelta(minutes=5) else []
        if not ready:
            return 0
    client = client or get_llm_client(settings.llm_provider, settings.openai_api_key, settings.openai_model,
                                      settings.ollama_base_url, settings.ollama_model)
    try:
        CoachAgent(settings, client, user_id)._count_request()
    except RuntimeError:
        return 0
    turns = [{"role": role, "text": text} for row in ready for role, text in
             (("athlete", row[1]), ("coach", row[2]))]
    try:
        count = extract_suggestions(settings.db_path, user_id, turns, client)
    except Exception:
        return 0
    last_id = int(ready[-1][0])
    with sqlite3.connect(settings.db_path) as db:
        db.execute("INSERT INTO coach_memory_extraction_state(user_id,processed_through_id,updated_at) "
                   "VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                   "processed_through_id=excluded.processed_through_id,updated_at=excluded.updated_at",
                   (user_id, last_id, utc_now.isoformat()))
    return count
