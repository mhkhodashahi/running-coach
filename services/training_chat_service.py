"""DB-backed, evidence-grounded coach chat for Telegram and Streamlit."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from coach.agent import CoachAgent
from config import Settings, get_settings
from llm.factory import get_llm_client
from services.running_coach_memory import load_running_memory


@dataclass(frozen=True)
class TrainingChatReply:
    text: str
    used_llm: bool
    evidence: tuple[dict[str, str], ...] = ()
    activity_ids: tuple[int, ...] = ()
    follow_ups: tuple[str, ...] = ()
    tool_calls: tuple[dict[str, Any], ...] = ()


class TrainingChatService:
    """Expose the same coach agent to both chat surfaces."""

    def __init__(self, settings: Settings | None = None, llm_client: Any | None = None) -> None:
        self.settings = settings or get_settings()
        self.llm_client = llm_client or get_llm_client(
            self.settings.llm_provider, self.settings.openai_api_key, self.settings.openai_model,
            self.settings.ollama_base_url, self.settings.ollama_model,
        )

    def answer(self, question: str, user_id: int | None = None,
               activity_id: int | None = None) -> TrainingChatReply:
        if not question.strip():
            return TrainingChatReply("Ask me a training question.", False)
        agent = CoachAgent(self.settings, self.llm_client, user_id or self.settings.default_user_id)
        try:
            result = agent.answer(question, activity_id=activity_id, running_memory=load_running_memory())
        except (RuntimeError, ValueError) as exc:
            return TrainingChatReply(str(exc), False)
        evidence = tuple(result.evidence)
        suffix = "\n\nEvidence: " + "; ".join(f"{item['metric']}: {item['display']}" for item in evidence[:4]) if evidence else ""
        return TrainingChatReply(_telegram_limit(result.answer + suffix), True, evidence,
                                 result.activity_ids, result.follow_ups, result.tool_calls)

    def history(self, user_id: int | None = None, limit: int = 20) -> list[dict[str, str]]:
        database = self.settings.db_path
        with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as connection:
            rows = connection.execute("SELECT question, answer, created_at FROM coach_chat_turns "
                                      "WHERE user_id=? ORDER BY id DESC LIMIT ?",
                                      (user_id or self.settings.default_user_id, min(max(limit, 1), 30))).fetchall()
        return [{"question": row[0], "answer": row[1], "created_at": row[2]} for row in reversed(rows)]


def _telegram_limit(text: str, limit: int = 3900) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit - 15].rstrip() + "\n\n[truncated]"
