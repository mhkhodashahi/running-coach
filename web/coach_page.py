"""Coach conversation view and explicit plan-request orchestration."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

from coach.guardrails import plan_change_question
from coach.planning import propose_requested_change
from coach.proposals import monday
from config import Settings
from db.repositories.agent import AgentRepository
from db.repositories.coach import CoachRepository
from db.session import session_scope
from metrics.sports import RECOMMENDABLE_SPORTS, sport_category
from services.coach_memory_service import list_memories, save_memory
from services.training_chat_service import TrainingChatReply, TrainingChatService
from web.formatting import short_date
from web.plan_page import plan_context
from web.today import sync_label
from web.view_models.coach import QUICK_QUESTIONS, coach_availability, coach_turns, context_chip
from worker.state import history as worker_history

COACH_DATA_LIST = ("Activities", "Laps", "Samples", "Health metrics", "Metrics snapshot",
                   "Goals", "Planned intents", "Plan", "Effort ratings", "Timeline notes",
                   "Running memory", "Active coach memories")


def coach_context(settings: Settings, day: date, *, reply: TrainingChatReply | None = None,
                  question: str | None = None, attached_id: int | None = None,
                  context: str = "today") -> dict[str, Any]:
    """Read one user's thread, recent sessions, plan and today's call count."""
    user_id = settings.default_user_id
    with session_scope(settings.db_url) as session:
        repository = CoachRepository(session)
        rows = repository.recent_activity_cards(user_id, day)
        calls = AgentRepository(session).call_count(user_id, day)
        owner = repository.activity_card(user_id, attached_id) if attached_id is not None else None
    recent = [{"id": row["id"], "date": short_date(row["date"]),
               "sport": sport_category(row["type"], day),
               "label": row["activity_name"] or row["type"].replace("_", " ").title()}
              for row in rows if sport_category(row["type"], day) in RECOMMENDABLE_SPORTS][:20]
    attached = next((item for item in recent if item["id"] == attached_id), None)
    if attached_id is not None and attached is None:
        if owner is None:
            raise ValueError("Attached session not found")
        attached = {"id": owner["id"], "date": short_date(owner["date"]),
                    "sport": sport_category(owner["type"], day),
                    "label": owner["activity_name"] or owner["type"].replace("_", " ").title()}
    plan = plan_context(settings, day)
    indexed = {item["date"]: item for week in plan["weeks"] for item in week["days"]}
    days = [indexed[(day + timedelta(days=offset)).isoformat()] for offset in range(7)]
    thread = TrainingChatService(settings).history(settings.default_user_id)
    referenced = {activity_id for turn in thread for activity_id in turn["activity_ids"]}
    if referenced:
        with session_scope(settings.db_url) as session:
            card_rows = CoachRepository(session).activity_cards(user_id, list(referenced))
        cards = {identifier: {"id": identifier, "label": row["activity_name"] or
                  row["type"].replace("_", " ").title(), "date": short_date(row["date"]),
                  "sport": sport_category(row["type"], day)} for identifier, row in card_rows.items()}
        for turn in thread:
            turn["cards"] = [cards[activity_id] for activity_id in turn["activity_ids"] if activity_id in cards]
    follow_ups = reply.follow_ups if reply else ("How has my recovery changed?",
                 "What does my latest activity show?") if thread else ()
    availability = coach_availability(settings.llm_provider, calls, settings.coach_daily_call_limit,
                                      settings.allow_remote_llm and settings.remote_athlete_data_approved)
    return {"thread": coach_turns(thread), "reply": reply, "follow_ups": follow_ups,
            "question": question, "attached_id": attached_id,
            "sessions": recent, "days": days, "data_list": COACH_DATA_LIST,
            "calls": calls, "call_limit": settings.coach_daily_call_limit,
            "availability": availability, "context_kind": context,
            "selected_context": context_chip(context, attached),
            "quick_questions": QUICK_QUESTIONS,
            "sync": sync_label(settings, day),
            "messages": [row for row in worker_history(settings.db_path, settings.default_user_id)
                         if row["message_text"] and row["job"] in ("morning", "day_review", "weekly_review")],
            "memory_suggestions": [row for row in list_memories(settings.db_path, settings.default_user_id)
                                   if row["status"] == "suggested"]}


def ask_coach(settings: Settings, day: date, question: str, activity_id: int | None,
              llm: Any = None) -> TrainingChatReply:
    """A plan-change request creates a proposal, not a plan edit."""
    question = question.strip()
    if not 1 <= len(question) <= 500:
        raise ValueError("Ask a question of at most 500 characters")
    lowered = question.casefold()
    prefix = next((value for value in ("remember:", "merk dir:") if lowered.startswith(value)), None)
    if prefix:
        remembered = " ".join(question[len(prefix):].split())
        if not remembered:
            raise ValueError("Add the memory text after Remember:")
        memory_id = save_memory(settings.db_path, settings.default_user_id, remembered)
        text = "I saved that as an active memory."
        _save_chat_turn(settings, question, text, (),
                        ({"name": "save_coach_memory", "arguments": {"memory_id": memory_id}},),
                        "code", "none", "remember-v1")
        return TrainingChatReply(text, False)
    if activity_id is not None:
        with session_scope(settings.db_url) as session:
            if CoachRepository(session).activity_card(settings.default_user_id, activity_id) is None:
                raise ValueError("Attached session not found")
    if not plan_change_question(question):
        return TrainingChatService(settings, llm_client=llm).answer(question, settings.default_user_id, activity_id)
    proposal = propose_requested_change(question, monday(day), settings=settings,
                                        user_id=settings.default_user_id, llm=llm, today=day)
    text = "I drafted a plan-change proposal for your review. Nothing has been applied. Review it in Plan."
    evidence = tuple(proposal["facts"][:4])
    _save_chat_turn(settings, question, text, evidence,
                    ({"name": "propose_requested_change", "arguments": {"week": monday(day).isoformat()}},),
                    settings.llm_provider, settings.openai_model if settings.llm_provider == "openai" else
                    settings.ollama_model, "chat-plan-v1")
    return TrainingChatReply(text, True, evidence, (), ("What changed in the proposal?",), ())


def _save_chat_turn(settings: Settings, question: str, answer: str,
                    evidence: tuple[dict[str, Any], ...] | list[dict[str, Any]],
                    tool_calls: tuple[dict[str, Any], ...], provider: str, model: str,
                    prompt_version: str) -> None:
    with session_scope(settings.db_url) as session:
        AgentRepository(session).save_chat_turn(
            settings.default_user_id, question, answer, json.dumps(evidence), json.dumps([]),
            json.dumps(tool_calls), provider, model, prompt_version, datetime.now(UTC))
