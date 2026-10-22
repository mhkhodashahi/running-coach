"""Read legacy opinions and validate numeric evidence for v2 opinions."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

from llm.schemas import CoachOpinionV2, CoachOpinionV21, OpinionIntent

NUMBER = re.compile(r"(?<![\w])(?:\d{1,2}:\d{2}|\d+h\s*\d+m|\d+(?:\.\d+)?)(?![\d.:])", re.IGNORECASE)


class _LegacyCoachOpinionV2(CoachOpinionV2):
    intent: OpinionIntent | None = None


def _field(row: Any, name: str) -> Any:
    return row.get(name) if isinstance(row, dict) else getattr(row, name, None)


def load_opinion(row: Any) -> CoachOpinionV2:
    """Return a v2 view of a stored opinion without updating the source row."""
    payload = json.loads(_field(row, "payload_json"))
    if _field(row, "schema_version") is not None:
        return CoachOpinionV2.model_validate(payload)

    def points(key: str) -> list[dict[str, str]]:
        return [{"lead": str(item), "detail": ""} for item in payload.get(key, []) or []]

    confidence = payload.get("confidence")
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0
    conclusion = str(payload.get("brutally_honest_conclusion") or "")
    mapped = {
        "headline": str(payload.get("headline") or conclusion or payload.get("overall_assessment") or ""),
        "confidence": "high" if confidence >= 70 else "medium" if confidence >= 40 else "low",
        "conclusion": conclusion,
        "assessment": str(payload.get("overall_assessment") or ""),
        "worked": points("what_was_good"),
        "fix": points("mistakes_or_inefficiencies"),
        "sections": {
            "pacing": str(payload.get("pacing_analysis") or ""),
            "aerobic": str(payload.get("aerobic_efficiency_analysis") or ""),
            "recovery": str(payload.get("recovery_analysis") or ""),
            "mental": str(payload.get("mental_performance_insights") or ""),
        },
        "recommendations": [{"text": str(item), "action": "none", "session": {}}
                            for item in payload.get("training_recommendations", []) or []],
        "evidence": [{"metric": "", "value": str(item), "source": "legacy"}
                     for item in payload.get("evidence", []) or []],
    }
    return _LegacyCoachOpinionV2.model_validate(mapped)


def _numbers(text: str) -> set[str]:
    found = set()
    for match in NUMBER.finditer(text):
        raw = match.group().lower().replace(" ", "")
        if ":" in raw or "h" in raw:
            found.add(raw)
        else:
            value = Decimal(raw)
            if "." in raw or value >= 10:
                found.add(format(value.normalize(), "f"))
    return found


def unsupported_numbers(opinion: CoachOpinionV2) -> tuple[str, ...]:
    """Find numbers in judgment text absent from all evidence values."""
    supported = set().union(*(_numbers(item.value) for item in opinion.evidence)) if opinion.evidence else set()
    claims = [point.lead + " " + point.detail for point in (*opinion.worked, *opinion.fix)]
    claims.extend((opinion.sections.pacing, opinion.sections.aerobic,
                   opinion.sections.recovery, opinion.sections.mental))
    return tuple(sorted(set().union(*(_numbers(text) for text in claims)) - supported))


def _context_scalars(value: Any, path: str = "") -> dict[str, str]:
    if isinstance(value, dict):
        result: dict[str, str] = {}
        for key, child in value.items():
            result.update(_context_scalars(child, f"{path}.{key}" if path else key))
        return result
    if isinstance(value, list):
        result = {}
        for index, child in enumerate(value):
            result.update(_context_scalars(child, f"{path}[{index}]"))
        return result
    if value is None or isinstance(value, bool):
        return {}
    return {path: str(value)}


def unsupported_evidence(opinion: CoachOpinionV21, context: dict[str, Any]) -> tuple[str, ...]:
    """Find evidence whose source path and verbatim value do not match context."""
    scalars = _context_scalars(context)
    return tuple(f"{item.source}={item.value}" for item in opinion.evidence
                 if scalars.get(item.source) != item.value)


def opinion_rule_errors(opinion: CoachOpinionV21, context: dict[str, Any]) -> tuple[str, ...]:
    """Check v2.1 rules that depend on the selected activity's evidence."""
    errors: list[str] = []
    if opinion.intent is None or opinion.intent.planned != context.get("planned_intent"):
        errors.append("intent.planned must match planned_intent")
    selected = context.get("selected_activity") or {}
    stream = context.get("stream_analysis") or {}
    laps = context.get("lap_analysis") or {}
    session = (context.get("metrics_snapshot") or {}).get("activity_session") or {}
    available = {
        "Pacing": bool(selected.get("pace") or laps.get("available") or stream.get("pace")),
        "Intensity vs plan": bool(selected.get("avg_hr") or selected.get("training_effect") or stream.get("heart_rate")),
        "Aerobic stimulus": bool(selected.get("aerobic_effect") or session.get("load") or session.get("hr_zones")),
        "HR control": bool(selected.get("avg_hr") or stream.get("heart_rate")),
    }
    expected = [aspect for aspect, exists in available.items() if exists]
    if [item.aspect for item in opinion.verdicts] != expected:
        errors.append(f"verdict aspects must be exactly {expected}")
    if laps.get("available") or stream.get("available"):
        if not opinion.worked or not opinion.fix:
            errors.append("worked and fix each need an item when laps or streams exist")
    headline = opinion.headline.casefold()
    name = str(selected.get("activity_name") or "").casefold()
    location = str(selected.get("location") or "").casefold()
    if name and name in headline:
        errors.append("headline repeats activity name")
    title_words = {word for word in re.findall(r"[a-z]{4,}", name)
                   if word not in {"run", "running", "easy", "steady", "tempo", "recovery",
                                   "morning", "evening", "afternoon", "training", "workout"}}
    if (location and location in headline) or any(re.search(rf"\b{re.escape(word)}\b", headline) for word in title_words):
        errors.append("headline contains activity location or distinctive name")
    goal = context.get("active_goal") or {}
    goal_terms = [str(goal.get(key) or "").casefold() for key in ("name", "goal_label")]
    judgement = " ".join([opinion.headline, opinion.conclusion, opinion.assessment,
                          *(item.lead + " " + item.detail for item in (*opinion.worked, *opinion.fix)),
                          *opinion.sections.model_dump().values(),
                          *(item.aspect + " " + item.word for item in opinion.verdicts)]).casefold()
    if any(term and term in judgement for term in goal_terms):
        errors.append("long-term goal belongs only in recommendations")
    return tuple(errors)
