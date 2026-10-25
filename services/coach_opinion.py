"""Read legacy opinions and validate numeric evidence for v2 opinions."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

from llm.schemas import (
    CoachOpinionV2,
    CoachOpinionV21,
    CoachOpinionV22,
    CoachOpinionV23,
    OpinionDraftV22,
    OpinionDraftV23,
    OpinionIntent,
)
from services.coach_facts import Fact, IntentDecision, match_text_facts, unsupported_text_numbers

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
    sentence = re.match(r"(.{0,140}?[.!?])(?:\s+|$)(.*)", conclusion, re.DOTALL)
    first, rest = (sentence.group(1), sentence.group(2)) if sentence else (conclusion[:140], conclusion[140:])
    legacy_headline = first.strip() if conclusion else ""
    mapped = {
        "headline": str(payload.get("headline") or legacy_headline or payload.get("overall_assessment") or ""),
        "confidence": "high" if confidence >= 70 else "medium" if confidence >= 40 else "low",
        "conclusion": rest.strip() if not payload.get("headline") else conclusion,
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


def opinion_rule_errors(opinion: CoachOpinionV2, context: dict[str, Any]) -> tuple[str, ...]:
    """Check versioned opinion rules that depend on the activity context."""
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
        "Aerobic stimulus": bool(selected.get("aerobic_effect")
                                 or (session.get("load") or {}).get("value") is not None
                                 or any(zone.get("percent") is not None for zone in session.get("hr_zones") or [])),
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
    if context.get("prompt_version") == "opinion-v2.4":
        recommendations = " ".join(item.text for item in opinion.recommendations).casefold()
        stored_name = str(goal.get("name") or "").casefold().strip()
        if stored_name and stored_name in recommendations:
            errors.append("refer to the goal by type and distance, never its stored name")
        if re.search(r"\bgoal\b", recommendations):
            goal_fact = next((fact["display"] for fact in context.get("facts_pack") or []
                              if fact["id"] == "GOAL"), None)
            goal_distance = goal.get("target_distance_km")
            if goal_fact is None and goal_distance is not None:
                goal_fact = f"your {float(goal_distance):g}K goal"
            if goal_fact and goal_fact.casefold() not in recommendations:
                errors.append("goal reference must use its type and distance")
    if isinstance(opinion, CoachOpinionV23):
        facts = {fact["id"]: fact["display"] for fact in context.get("facts_pack") or []}
        if laps.get("available") or stream.get("available"):
            if not 2 <= len(opinion.worked) <= 4:
                errors.append("worked needs 2–4 items when laps or streams exist")
            if not 1 <= len(opinion.fix) <= 3:
                errors.append("fix needs 1–3 items when laps or streams exist")
        if any(fact_id == "READINESS" or fact_id.startswith(("HRV_", "RHR_", "SLEEP_", "LOAD_"))
               for fact_id in facts) and not opinion.sections.recovery.strip():
            errors.append("recovery section is required when recovery or load facts exist")
        status = facts.get("LOAD_RATIO_STATUS", "")
        if status.startswith(("below", "above")) and re.sub(r"\s+", "", status.casefold()) not in re.sub(
                r"\s+", "", opinion.sections.recovery.casefold()):
            errors.append("recovery section must state the out-of-range load ratio status")
        if "CONSERVATIVE_START" in facts:
            pacing_text = " ".join((opinion.assessment, opinion.sections.pacing,
                                    *(item.lead + " " + item.detail for item in opinion.worked)))
            compact = re.sub(r"\s+", "", pacing_text.casefold())
            first_pace = re.sub(r"\s+", "", facts.get("FIRST_FULL_KM_PACE", "").casefold())
            if "conservative" not in pacing_text.casefold() or not first_pace or first_pace not in compact:
                errors.append("mention the conservative first kilometre with its pace")
        if opinion.intent and opinion.intent.planned is None and opinion.intent.detected not in {"easy", "recovery"}:
            cap = facts.get("ZONE_Z2_UPPER_BPM")
            if cap is None or not any(
                "if this was meant as an easy run," in (item.lead + " " + item.detail).casefold()
                and re.sub(r"\s+", "", cap.casefold()) in re.sub(
                    r"\s+", "", (item.lead + " " + item.detail).casefold())
                for item in opinion.fix
            ):
                errors.append("fix needs the conditional easy-run line with the Z2 upper bpm fact")
    return tuple(errors)


def draft_validation_errors(draft: OpinionDraftV22, facts: list[Fact]) -> tuple[str, ...]:
    """Reject unknown citations and any model-written number absent from facts."""
    known = {fact["id"] for fact in facts}
    errors = [f"Unknown evidence ID: {fact_id}" for fact_id in draft.evidence_ids if fact_id not in known]
    if len(set(draft.evidence_ids)) != len(draft.evidence_ids):
        errors.append("Duplicate evidence IDs")
    cited = [fact for fact in facts if fact["id"] in draft.evidence_ids]
    texts = [draft.headline, draft.conclusion, draft.assessment,
             *(item.word for item in draft.verdicts),
             *(item.lead + " " + item.detail for item in (*draft.worked, *draft.fix)),
             *draft.sections.model_dump().values(),
             *(item.text for item in draft.recommendations)]
    for text in texts:
        unsupported = unsupported_text_numbers(text, cited)
        if unsupported:
            errors.append("Unsupported numbers: " + ", ".join(unsupported))
    for item in draft.recommendations:
        if item.action == "add_to_plan":
            duration = item.session.duration_min
            hr_cap = item.session.hr_cap_bpm
            unsupported = unsupported_text_numbers(f"{duration} min; {hr_cap} bpm", cited)
            if unsupported:
                errors.append("Unsupported session numbers: " + ", ".join(unsupported))
    return tuple(errors)


def assemble_opinion(draft: OpinionDraftV22, facts: list[Fact], decision: IntentDecision,
                     planned_intent: str | None, data_notes: list[str]) -> CoachOpinionV22:
    """Convert cited fact IDs to immutable stored evidence, intent and notes."""
    errors = draft_validation_errors(draft, facts)
    if errors:
        raise ValueError("; ".join(errors))
    by_id = {fact["id"]: fact for fact in facts}
    payload = draft.model_dump(exclude={"evidence_ids"})
    payload.update({
        "schema_version": 2,
        "confidence": "medium",
        "intent": {"planned": planned_intent, "detected": decision.intent},
        "data_notes": list(data_notes),
        "evidence": [{"metric": by_id[fact_id]["metric"], "value": by_id[fact_id]["display"],
                      "source": by_id[fact_id]["source"]} for fact_id in draft.evidence_ids],
    })
    return CoachOpinionV22.model_validate(payload)


def collect_v23_evidence_ids(draft: OpinionDraftV23, facts: list[Fact]) -> list[str]:
    """Resolve numeric claims and per-recommendation targets to known fact IDs."""
    by_id = {fact["id"]: fact for fact in facts}
    ids = list(draft.evidence_ids)
    errors = [f"Unknown evidence ID: {fact_id}" for fact_id in ids if fact_id not in by_id]
    if len(ids) != len(set(ids)):
        errors.append("Duplicate evidence IDs")
    texts = [draft.headline, draft.conclusion, draft.assessment,
             *(item.word for item in draft.verdicts),
             *(item.lead + " " + item.detail for item in (*draft.worked, *draft.fix)),
             *draft.sections.model_dump().values()]
    for recommendation in draft.recommendations:
        rec_ids = recommendation.evidence_ids
        errors.extend(f"Unknown recommendation evidence ID: {fact_id}" for fact_id in rec_ids
                      if fact_id not in by_id)
        if len(rec_ids) != len(set(rec_ids)):
            errors.append("Duplicate recommendation evidence IDs")
        target_ids = [fact_id for fact_id in rec_ids if fact_id in by_id and (
            "PACE" in fact_id or "DURATION" in fact_id or fact_id.endswith("UPPER_BPM")
            or fact_id == "Z2_LOWER_HALF_CAP")]
        compact_text = re.sub(r"\s+", "", recommendation.text.casefold())
        if not any(re.sub(r"\s+", "", by_id[fact_id]["display"].casefold()) in compact_text
                   for fact_id in target_ids):
            errors.append("recommendation needs a cited pace, duration or HR-cap target in its text")
        if re.search(r"\bnext (?:easy |steady |tempo |recovery )?(?:run|session)\b", recommendation.text,
                     re.IGNORECASE) and recommendation.action != "add_to_plan":
            errors.append("a next session requires add_to_plan")
        if recommendation.action == "add_to_plan":
            session = recommendation.session
            duration = f"{session.duration_min} min"
            hr_cap = f"{session.hr_cap_bpm} bpm"
            for value in (duration, hr_cap):
                if not any(fact["display"] == value for fact in facts):
                    errors.append(f"Unsupported session target: {value}")
            texts.append(f"{duration}; {hr_cap}")
        texts.append(recommendation.text)
        ids.extend(fact_id for fact_id in rec_ids if fact_id not in ids)
    for item in texts:
        leaked_ids = [fact_id for fact_id in by_id if re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(fact_id)}(?![A-Za-z0-9_])", item)]
        if leaked_ids:
            errors.append("Fact IDs must not appear in opinion text: " + ", ".join(leaked_ids))
        matched, unsupported = match_text_facts(item, facts, tuple(ids))
        ids.extend(fact_id for fact_id in matched if fact_id not in ids)
        if unsupported:
            errors.append("Unsupported numbers: " + ", ".join(unsupported))
    z2_cap = by_id.get("ZONE_Z2_UPPER_BPM")
    if z2_cap is not None:
        cap_display = re.sub(r"\s+", "", z2_cap["display"].casefold())
        for item in draft.fix:
            line = (item.lead + " " + item.detail).casefold()
            if ("if this was meant as an easy run," in line
                    and cap_display in re.sub(r"\s+", "", line)
                    and "ZONE_Z2_UPPER_BPM" not in ids):
                ids.append("ZONE_Z2_UPPER_BPM")
    if errors:
        raise ValueError("; ".join(errors))
    return ids


def assemble_opinion_v23(draft: OpinionDraftV23, facts: list[Fact], decision: IntentDecision,
                         planned_intent: str | None, data_notes: list[str]) -> CoachOpinionV23:
    """Assemble the stored v2 contract from a validated v2.3 draft."""
    ids = collect_v23_evidence_ids(draft, facts)
    by_id = {fact["id"]: fact for fact in facts}
    payload = draft.model_dump(exclude={"evidence_ids", "recommendations"})
    payload.update({
        "schema_version": 2,
        "confidence": "medium",
        "intent": {"planned": planned_intent, "detected": decision.intent},
        "data_notes": list(data_notes),
        "recommendations": [{"text": item.text, "action": item.action, "session": item.session.model_dump()}
                            for item in draft.recommendations],
        "evidence": [{"metric": by_id[fact_id]["metric"], "value": by_id[fact_id]["display"],
                      "source": by_id[fact_id]["source"]} for fact_id in ids],
    })
    return CoachOpinionV23.model_validate(payload)
