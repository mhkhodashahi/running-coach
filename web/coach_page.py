"""Coach conversation view and explicit plan-request orchestration."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from typing import Any

from coach.guardrails import plan_change_question
from coach.planning import propose_requested_change
from coach.proposals import monday
from config import Settings
from metrics.sports import RECOMMENDABLE_SPORTS, sport_category
from services.training_chat_service import TrainingChatReply, TrainingChatService
from web.formatting import short_date
from web.plan_page import plan_context
from web.today import sync_label
from worker.state import history as worker_history

COACH_DATA_LIST = ("Activities", "Laps", "Samples", "Health metrics", "Metrics snapshot",
                   "Goals", "Planned intents", "Plan", "Effort ratings", "Running memory")


def _db(settings: Settings) -> sqlite3.Connection:
    connection = sqlite3.connect(settings.db_path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def coach_context(settings: Settings, day: date, *, reply: TrainingChatReply | None = None,
                  question: str | None = None, attached_id: int | None = None) -> dict[str, Any]:
    """Read one user's thread, recent sessions, plan and today's call count."""
    with _db(settings) as connection:
        rows = connection.execute("SELECT id,date,type,activity_name,duration FROM activities WHERE user_id=? "
                                  "AND date<=? ORDER BY date DESC,id DESC LIMIT 120",
                                  (settings.default_user_id, day.isoformat())).fetchall()
        recent = [{"id": row["id"], "date": short_date(row["date"]),
                   "sport": sport_category(row["type"], day),
                   "label": row["activity_name"] or row["type"].replace("_", " ").title()}
                  for row in rows if sport_category(row["type"], day) in RECOMMENDABLE_SPORTS][:20]
        if attached_id is not None and not any(item["id"] == attached_id for item in recent):
            owner = connection.execute("SELECT 1 FROM activities WHERE id=? AND user_id=?",
                                       (attached_id, settings.default_user_id)).fetchone()
            if owner is None:
                raise ValueError("Attached session not found")
        calls = connection.execute("SELECT COUNT(*) FROM coach_llm_calls WHERE user_id=? AND local_day=?",
                                   (settings.default_user_id, day.isoformat())).fetchone()[0]
    plan = plan_context(settings, day)
    indexed = {item["date"]: item for week in plan["weeks"] for item in week["days"]}
    days = [indexed[(day + timedelta(days=offset)).isoformat()] for offset in range(7)]
    thread = TrainingChatService(settings).history(settings.default_user_id)
    referenced = {activity_id for turn in thread for activity_id in turn["activity_ids"]}
    if referenced:
        with _db(settings) as connection:
            placeholders = ",".join("?" for _ in referenced)
            cards = {row["id"]: {"id": row["id"], "label": row["activity_name"] or
                      row["type"].replace("_", " ").title(), "date": short_date(row["date"])}
                     for row in connection.execute(
                         f"SELECT id,date,type,activity_name FROM activities WHERE user_id=? AND id IN ({placeholders})",
                         (settings.default_user_id, *referenced))}
        for turn in thread:
            turn["cards"] = [cards[activity_id] for activity_id in turn["activity_ids"] if activity_id in cards]
    follow_ups = reply.follow_ups if reply else ("How has my recovery changed?",
                 "What does my latest activity show?") if thread else ()
    return {"thread": thread, "reply": reply, "follow_ups": follow_ups,
            "question": question, "attached_id": attached_id,
            "sessions": recent, "days": days, "data_list": COACH_DATA_LIST,
            "calls": calls, "call_limit": settings.coach_daily_call_limit,
            "sync": sync_label(settings, day),
            "messages": [row for row in worker_history(settings.db_path, settings.default_user_id)
                         if row["message_text"] and row["job"] in ("morning", "day_review", "weekly_review")]}


def ask_coach(settings: Settings, day: date, question: str, activity_id: int | None,
              llm: Any = None) -> TrainingChatReply:
    """A plan-change request creates a proposal, not a plan edit."""
    question = question.strip()
    if not 1 <= len(question) <= 500:
        raise ValueError("Ask a question of at most 500 characters")
    if activity_id is not None:
        with _db(settings) as connection:
            if connection.execute("SELECT 1 FROM activities WHERE id=? AND user_id=?",
                                  (activity_id, settings.default_user_id)).fetchone() is None:
                raise ValueError("Attached session not found")
    if not plan_change_question(question):
        return TrainingChatService(settings, llm_client=llm).answer(question, settings.default_user_id, activity_id)
    proposal = propose_requested_change(question, monday(day), settings=settings,
                                        user_id=settings.default_user_id, llm=llm, today=day)
    text = "I drafted a plan-change proposal for your review. Nothing has been applied. Review it in Plan."
    evidence = tuple(proposal["facts"][:4])
    with sqlite3.connect(settings.db_path) as connection:
        connection.execute("INSERT INTO coach_chat_turns(user_id,question,answer,evidence_json,activity_ids_json,"
                           "tool_calls_json,model_provider,model_name,prompt_version,created_at) "
                           "VALUES(?,?,?,?,?,?,?,?,?,?)",
                           (settings.default_user_id, question, text, json.dumps(evidence), json.dumps([]),
                            json.dumps([{"name": "propose_requested_change", "arguments": {"week": monday(day).isoformat()}}]),
                            settings.llm_provider, settings.openai_model if settings.llm_provider == "openai" else
                            settings.ollama_model, "chat-plan-v1", datetime.now(UTC).replace(tzinfo=None).isoformat()))
    return TrainingChatReply(text, True, evidence, (), ("What changed in the proposal?",), ())
