"""Read legacy opinions and validate numeric evidence for v2 opinions."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

from llm.schemas import CoachOpinionV2, OpinionIntent

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
