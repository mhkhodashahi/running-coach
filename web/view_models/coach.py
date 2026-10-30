"""Pure Coach page presentation and availability rules."""

from __future__ import annotations

import re
from typing import Any

from coach.guardrails import plan_change_question
from web.view_models.today import format_chip

CONTEXT_LABELS = {"today": "About: today", "training": "About: this week",
                  "insights": "About: recent recovery"}
QUICK_QUESTIONS = ("Why is today an easy day?", "How has my recovery changed?",
                   "What should my next run be?")
QUESTION_PREFIXES = {"today": "About today: ", "training": "About this week: ",
                     "insights": "About recent recovery: "}


def plain_coach_text(value: str) -> str:
    """Strip model markdown; Jinja still HTML-escapes the returned text."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    text = re.sub(r"(?m)^\s*[-*+]\s+", "- ", text)
    text = re.sub(r"\*\*|__|\*|`", "", text)
    text = re.sub(r"(?<!\w)_(?!\s)|_(?!\w)", "", text)
    text = " ".join(part for part in re.split(r"(?<=[.!?])\s+", text)
                    if not re.search(r"\b(?:load ratio|acute:chronic|ratio\s+\d)\b", part, re.IGNORECASE))
    return text.strip().strip('"“”') or "This earlier answer used a load measure I no longer show."


def coach_availability(provider: str, calls: int, limit: int, remote_allowed: bool) -> dict[str, Any]:
    """Describe whether a question can be sent without exposing provider credentials."""
    remote = provider in ("openai", "chatgpt")
    if calls >= limit:
        reason = "Today's coach question limit has been reached. Try again tomorrow."
    elif remote and not remote_allowed:
        reason = "Remote coaching is off. Approve athlete-data sharing in .env before asking."
    elif provider not in ("openai", "chatgpt", "ollama"):
        reason = "Choose a coach provider in .env before asking."
    else:
        reason = None
    return {"disabled": reason is not None, "reason": reason,
            "provider_label": "Remote coach" if remote else "Local coach" if provider == "ollama" else
            "No provider", "usage": f"{calls} of {limit} questions today"}


def context_chip(context: str, activity: dict[str, Any] | None = None) -> dict[str, str]:
    """A linked context label for the composer or a stored turn."""
    if activity:
        sport = "run" if activity.get("sport") == "running" else "session"
        return {"label": f"About: this {sport} · {activity['date']}",
                "href": f"/activities/{activity['id']}"}
    return {"label": CONTEXT_LABELS.get(context, CONTEXT_LABELS["today"]),
            "href": {"today": "/", "training": "/plan", "insights": "/trends"}.get(context, "/")}


def context_question(question: str, context: str) -> str:
    """Preserve the context convention used by the existing panel endpoints."""
    return QUESTION_PREFIXES.get(context, "") + question.strip()


def coach_evidence_chip(fact: dict[str, str]) -> dict[str, str] | None:
    """Use the same display vocabulary as the Today coach panel for stored facts."""
    metric = str(fact.get("metric") or "Evidence")
    normalized = metric.casefold().replace("_", " ")
    fact_id = fact.get("id") or {
        "readiness": "READINESS", "recovery": "READINESS", "load ratio": "LOAD_RATIO",
    }.get(normalized, "")
    if fact_id in ("LOAD_RATIO", "LOAD_RATIO_STATUS"):
        return None
    return format_chip({"id": fact_id, "metric": metric,
                        "display": str(fact.get("display") or ""),
                        "source": str(fact.get("source") or "")})


def coach_turns(thread: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Present stored turns without editing their persisted question or answer."""
    result = []
    for turn in thread:
        question = str(turn["question"])
        context = "today"
        for kind, prefix in QUESTION_PREFIXES.items():
            if question.startswith(prefix):
                context, question = kind, question[len(prefix):]
                break
        cards = turn.get("cards") or []
        chip = context_chip(context, cards[0]) if cards else context_chip(context)
        answer = str(turn["answer"])
        proposed = "proposal" in answer.lower() and "not been applied" in answer.lower()
        evidence_chips = (coach_evidence_chip(fact) for fact in turn.get("evidence") or [])
        result.append({**turn, "display_question": question, "context_chip": chip,
                       "evidence_chips": tuple(item for item in evidence_chips if item is not None),
                       "proposal_link": proposed,
                       "suggest_change": not proposed and plan_change_question(answer)
                       and len(answer) <= 470})
    return tuple(result)


def proposed_change_question(answer: str) -> str:
    """Turn an athlete-selected suggestion into an explicit proposal request."""
    compact = re.sub(r"\s+", " ", answer).strip()
    if not plan_change_question(compact):
        raise ValueError("This answer does not describe a plan change")
    return "Change my plan: " + compact[:470]
