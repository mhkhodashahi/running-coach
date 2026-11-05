"""DB-backed, evidence-grounded coach chat for Telegram and Streamlit."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from coach.agent import CoachAgent
from config import Settings, get_settings
from db.repositories.chat import ChatRepository
from db.session import session_scope
from llm.factory import get_llm_client
from services.coach_memory_service import memory_context
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
            persistent = memory_context(self.settings.db_path, user_id or self.settings.default_user_id)
            legacy = load_running_memory()
            context = "\n".join(value for value in (persistent, legacy) if value)
            result = agent.answer(question, activity_id=activity_id, running_memory=context)
        except (RuntimeError, ValueError) as exc:
            return TrainingChatReply(str(exc), False)
        evidence = tuple(result.evidence)
        suffix = "\n\nEvidence: " + "; ".join(f"{item['metric']}: {item['display']}" for item in evidence[:4]) if evidence else ""
        return TrainingChatReply(_telegram_limit(result.answer + suffix), True, evidence,
                                 result.activity_ids, result.follow_ups, result.tool_calls)

    def history(self, user_id: int | None = None, limit: int = 20) -> list[dict[str, Any]]:
        url = f"sqlite:///file:{self.settings.db_path.resolve()}?mode=ro&uri=true"
        with session_scope(url) as session:
            rows = ChatRepository(session).recent_turns(
                user_id or self.settings.default_user_id, min(max(limit, 1), 30)
            )
        return [{"question": row["question"], "answer": row["answer"],
                 "evidence": json.loads(row["evidence_json"]),
                 "activity_ids": json.loads(row["activity_ids_json"]), "created_at": row["created_at"],
                 "tool_calls": json.loads(row["tool_calls_json"])} for row in rows]


def _telegram_limit(text: str, limit: int = 3900) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit - 15].rstrip() + "\n\n[truncated]"
