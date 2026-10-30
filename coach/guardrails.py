"""Deterministic post-generation safety rules for coach chat."""

from __future__ import annotations

import re
from dataclasses import dataclass

HARD_ADVICE = re.compile(r"\b(?:train hard|hard session|intervals?|tempo|race|sprints?|vo2max|threshold)\b", re.I)
DIAGNOSIS = re.compile(r"\b(?:you (?:have|likely have|are suffering from)|diagnos(?:is|ed with)|"
                       r"(?:covid|flu|anemia|anaemia|myocarditis|overtraining syndrome))\b", re.I)
PLAN_CHANGE = re.compile(
    r"\b(?:change|move|edit|update|reschedule|cancel|delete|add|swap|make)\b.{0,70}"
    r"\b(?:plan|schedule|session|workout|run|gym|saturday|monday|tuesday|wednesday|"
    r"thursday|friday|sunday|tomorrow|next week)\b", re.I)


@dataclass(frozen=True)
class GuardrailContext:
    illness: bool
    load_ratio: float | None
    plan_change_requested: bool


def plan_change_question(question: str) -> bool:
    return bool(PLAN_CHANGE.search(question))


def diagnosis_sentences(answer: str) -> tuple[str, ...]:
    return tuple(sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", answer)
                 if DIAGNOSIS.search(sentence))


def guardrail_errors(answer: str, context: GuardrailContext) -> tuple[str, ...]:
    errors = []
    if diagnosis_sentences(answer):
        errors.append("Do not diagnose or name a medical condition")
    if context.illness and HARD_ADVICE.search(answer):
        errors.append("Illness signal: do not recommend hard training or racing")
    elif context.load_ratio is not None and context.load_ratio > 1.5 and HARD_ADVICE.search(answer):
        errors.append("High training load: easy training or rest only")
    if context.plan_change_requested and not re.search(r"\bproposals?\b", answer, re.I):
        errors.append("Plan changes must be described as proposals")
    return tuple(errors)


def enforce_guardrails(answer: str, context: GuardrailContext) -> str:
    """Produce a safe answer after the single model retry has failed."""
    if context.plan_change_requested:
        return "I can suggest a plan change, but I cannot apply it. Plan changes come as proposals for you to accept or reject."
    if context.illness:
        return "Rest today. Your recovery signals suggest caution. If this persists, see a doctor."
    if context.load_ratio is not None and context.load_ratio > 1.5 and HARD_ADVICE.search(answer):
        return "Keep training easy or rest today. Your weekly load is above your usual level."
    sentences = [sentence for sentence in re.split(r"(?<=[.!?])\s+", answer)
                 if not DIAGNOSIS.search(sentence)]
    return " ".join(sentences).strip() or "I cannot give a reliable answer from the available data."
