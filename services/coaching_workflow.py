"""Goal-aware coaching workflow for daily and weekly decisions."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pandas as pd

from analytics.performance import build_training_snapshot
from config import get_settings
from db import repository
from llm.factory import get_llm_client
from llm.schemas import CoachingDecisionSchema, TelegramMessageSchema
from services.coaching_engine import (
    _daily_guidance,
    _training_effectiveness,
    _weekly_guidance,
    build_rule_recommendations,
)
from services.coaching_prompts import build_calendar_context, build_decision_prompt, build_telegram_prompt
from services.goal_service import GoalService
from services.llm_workflow import generate_structured_payload
from services.running_coach_memory import (
    build_memory_entry_from_decision,
    load_running_memory,
    update_running_memory,
)
from services.telegram_service import TelegramService


def _latest_reference_date(activities_df: pd.DataFrame, health_df: pd.DataFrame) -> date:
    candidates: list[pd.Timestamp] = []
    if not activities_df.empty:
        candidates.append(pd.to_datetime(activities_df["date"]).max())
    if not health_df.empty:
        candidates.append(pd.to_datetime(health_df["date"]).max())
    if not candidates:
        return date.today()
    return max(candidates).date()


def _latest_day_activities_summary(activities_df: pd.DataFrame) -> str:
    if activities_df.empty:
        return "No recent activity was available."
    activities = activities_df.copy()
    activities["date"] = pd.to_datetime(activities["date"])
    latest_day = activities["date"].dt.normalize().max()
    day_activities = activities[activities["date"].dt.normalize() == latest_day].sort_values("date")
    parts = []
    for row in day_activities.itertuples():
        pace = getattr(row, "pace", None)
        pace_text = f" at {float(pace):.2f} min/km" if pd.notna(pace) else ""
        avg_hr = getattr(row, "avg_hr", None)
        hr_text = f", avg HR {float(avg_hr):.0f}" if pd.notna(avg_hr) else ""
        parts.append(
            f"{row.type} {float(row.distance):.1f} km in {float(row.duration):.0f} min{pace_text}{hr_text}"
        )
    total_distance = float(day_activities["distance"].fillna(0).sum())
    total_duration = float(day_activities["duration"].fillna(0).sum())
    return (
        f"Latest activity day ({latest_day.date()}): {len(day_activities)} activity/activities, "
        f"{total_distance:.1f} km and {total_duration:.0f} min total. " + "; ".join(parts) + "."
    )


def _risk_level(snapshot: dict[str, Any]) -> str:
    fatigue = snapshot.get("fatigue", {})
    readiness = snapshot.get("readiness", {})
    recovery = snapshot.get("recovery", {})
    if fatigue.get("level") == "high" or readiness.get("label") == "low" or recovery.get("sleep_score", 100) < 68:
        return "high"
    if fatigue.get("level") == "moderate" or readiness.get("label") == "building":
        return "moderate"
    return "low"


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _normalize_decision_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = {key: value for key, value in payload.items() if value not in (None, "")}
    for key in ("key_positives", "key_limiters", "evidence"):
        if key in normalized:
            normalized[key] = _normalize_string_list(normalized[key])
    confidence = normalized.get("confidence")
    if confidence is not None:
        try:
            normalized["confidence"] = float(confidence)
        except (TypeError, ValueError):
            normalized.pop("confidence", None)
    risk_level = str(normalized.get("risk_level", "")).lower().strip()
    if risk_level not in {"low", "moderate", "high"}:
        normalized.pop("risk_level", None)
    return normalized


def _normalize_message_payload(payload: dict[str, Any]) -> dict[str, str]:
    title = str(payload.get("message_title", "")).strip()
    body = str(payload.get("message_body", "")).strip()
    return {
        "message_title": title,
        "message_body": body,
    }


def _prior_decision_context(session, user_id: int) -> list[dict[str, Any]]:
    history = repository.coaching_decisions_dataframe(session, user_id)
    if history.empty:
        return []
    items: list[dict[str, Any]] = []
    for row in history.head(3).itertuples():
        try:
            payload = json.loads(row.payload_json)
        except Exception:
            payload = {}
        items.append(
            {
                "decision_date": str(pd.Timestamp(row.decision_date).date()),
                "decision_type": row.decision_type,
                "summary": payload.get("summary", row.summary),
                "priority": payload.get("priority"),
                "risk_level": payload.get("risk_level", row.risk_level),
            }
        )
    return items


def _fallback_decision(
    *,
    decision_type: str,
    goal: Any,
    snapshot: dict[str, Any],
    activities_df: pd.DataFrame,
    rules: list[str],
) -> dict[str, Any]:
    daily_advice, _ = _daily_guidance(snapshot)
    weekly_advice, _ = _weekly_guidance(snapshot)
    effectiveness = _training_effectiveness(snapshot)
    projection = snapshot.get("active_goal_projection") or {}
    gap_minutes = float(projection.get("gap_minutes", 0.0))
    confidence = float(projection.get("confidence", snapshot["prediction"]["confidence"]))
    risk_level = _risk_level(snapshot)
    readiness = snapshot["readiness"]
    fatigue = snapshot["fatigue"]
    recovery = snapshot["recovery"]
    goal_label = GoalService.label_for(getattr(goal, "goal_type", "running_pb"))

    if risk_level == "high":
        summary = f"Recovery is the main limiter right now, so the next coaching decision should protect consistency more than push intensity for the {goal_label}."
    elif gap_minutes > 0:
        summary = f"You are still behind the current {goal_label} target, so the plan should favor the clearest missing adaptation instead of adding random volume."
    else:
        summary = f"Your current training is broadly aligned with the {goal_label} target, so the priority is to keep progression steady without creating unnecessary fatigue."

    goal_alignment = (
        f"{goal_label} projection is {'on track' if gap_minutes <= 0 else f'about {gap_minutes:.1f} minutes behind target'} "
        f"with {confidence:.0f}% confidence."
    )
    evidence = [
        f"Readiness {readiness['score']:.0f} ({readiness['label']})",
        f"Fatigue {fatigue['score']:.0f} ({fatigue['level']})",
        f"Sleep score {recovery.get('sleep_score', 0):.0f}",
        f"Recovery time {recovery.get('recovery_time', 0):.0f} h",
        f"7-day mileage {snapshot['weekly_mileage']['7d']:.1f} km",
        f"Latest long run {snapshot['long_runs']['latest_long_run_km']:.1f} km",
    ]
    if projection:
        evidence.append(
            f"{goal_label} prediction {projection.get('predicted_time_minutes', 0):.1f} min vs target {projection.get('target_time_minutes', 0):.1f} min"
        )

    priority = rules[0] if rules else daily_advice
    yesterday_assessment = (
        f"{_latest_day_activities_summary(activities_df)} "
        f"Latest recovery markers show sleep score {recovery.get('sleep_score', 0):.0f}, body battery {recovery.get('body_battery', 0):.0f}, and recovery time {recovery.get('recovery_time', 0):.0f} h."
    )
    return {
        "summary": summary,
        "yesterday_assessment": yesterday_assessment,
        "tomorrow_recommendation": daily_advice,
        "weekly_outlook": weekly_advice if decision_type == "weekly" else f"This week: {weekly_advice}",
        "goal_alignment": goal_alignment,
        "risk_level": risk_level,
        "confidence": round(confidence, 1),
        "key_positives": list(effectiveness.get("working", [])),
        "key_limiters": list(effectiveness.get("limiters", [])),
        "evidence": evidence,
        "priority": priority,
        "daily_advice": daily_advice,
        "weekly_advice": weekly_advice,
        "training_effectiveness": effectiveness,
        "readiness_assessment": f"{readiness['label']} readiness with fatigue score {fatigue['score']}.",
        "rule_recommendations": rules,
    }


def _fallback_message_payload(goal: Any, decision_payload: dict[str, Any]) -> dict[str, str]:
    athlete_name = str(decision_payload.get("athlete_name") or "").strip()
    goal_label = GoalService.label_for(getattr(goal, "goal_type", "running_pb"))
    risk_level = str(decision_payload.get("risk_level", "moderate")).title()
    title = {
        "High": "Take it easy today",
        "Moderate": f"{goal_label} check-in",
        "Low": "Good day to stay steady",
    }.get(risk_level, f"{goal_label} check-in")

    opening = f"{athlete_name}, " if athlete_name else ""
    summary = str(decision_payload.get("summary", "")).strip()
    yesterday = str(decision_payload.get("yesterday_assessment", "")).strip()
    tomorrow = str(decision_payload.get("tomorrow_recommendation", "")).strip()
    weekly = str(decision_payload.get("weekly_outlook", "")).strip()
    goal_alignment = str(decision_payload.get("goal_alignment", "")).strip()
    evidence = [str(item).strip() for item in (decision_payload.get("evidence") or []) if str(item).strip()]
    positives = [str(item).strip() for item in (decision_payload.get("key_positives") or []) if str(item).strip()]
    limiters = [str(item).strip() for item in (decision_payload.get("key_limiters") or []) if str(item).strip()]

    body_lines = []
    if summary:
        body_lines.append(f"{opening}{summary}")
    if yesterday:
        body_lines.extend(["", f"Yesterday: {yesterday}"])
    if evidence:
        body_lines.extend(["", f"Body and training signals: {'; '.join(evidence[:6])}."])
    if goal_alignment:
        body_lines.extend(["", f"Goal impact: {goal_alignment}"])
    if positives or limiters:
        signal_parts = []
        if positives:
            signal_parts.append(f"working: {'; '.join(positives[:2])}")
        if limiters:
            signal_parts.append(f"limiting: {'; '.join(limiters[:2])}")
        body_lines.extend(["", f"What this means: {'. '.join(signal_parts)}."])
    if tomorrow:
        body_lines.extend(["", f"Next step: {tomorrow}"])
    if weekly:
        body_lines.extend(["", f"This week: {weekly}"])
    if decision_payload.get("priority"):
        body_lines.extend(["", f"Priority: {str(decision_payload['priority']).strip()}"])

    return {
        "message_title": title,
        "message_body": "\n".join(body_lines).strip(),
    }


class CoachingWorkflowService:
    """Goal-aware orchestration for coaching and digest generation."""

    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings
        self.goal_service = GoalService()
        self.telegram_service = TelegramService(settings)
        self.llm_client = get_llm_client(
            provider=settings.llm_provider,
            openai_api_key=settings.openai_api_key,
            openai_model=settings.openai_model,
            ollama_base_url=settings.ollama_base_url,
            ollama_model=settings.ollama_model,
        )

    def generate(
        self,
        session,
        user,
        *,
        decision_type: str = "daily",
        athlete_note: str = "",
        send_message: bool = False,
        recipient: str | None = None,
    ) -> dict[str, Any]:
        goal = self.goal_service.ensure_active_goal(session, user)
        activities_df = repository.activities_dataframe(session, user.id)
        health_df = repository.health_metrics_dataframe(session, user.id)
        prior_decisions = _prior_decision_context(session, user.id)
        snapshot = build_training_snapshot(user, activities_df, health_df, goal=goal)
        rules = build_rule_recommendations(snapshot)
        calendar_context = build_calendar_context(activities_df, health_df)
        running_memory = load_running_memory()

        decision = _fallback_decision(
            decision_type=decision_type,
            goal=goal,
            snapshot=snapshot,
            activities_df=activities_df,
            rules=rules,
        )

        system_prompt, user_prompt = build_decision_prompt(
            decision_type=decision_type,
            user=user,
            goal=goal,
            snapshot=snapshot,
            activities_df=activities_df,
            prior_decisions=prior_decisions,
            athlete_note=athlete_note,
            rules=rules,
            running_memory=running_memory,
        )
        decision_result = generate_structured_payload(
            llm_client=self.llm_client,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema=CoachingDecisionSchema,
            normalize=_normalize_decision_payload,
            unavailable_message="Coaching model unavailable",
        )
        if decision_result.warning:
            decision["llm_warning"] = decision_result.warning
        else:
            decision.update(decision_result.payload)

        decision["decision_type"] = decision_type
        decision["athlete_name"] = user.name
        decision["goal_name"] = goal.name
        decision["goal_type"] = goal.goal_type
        decision["goal_label"] = GoalService.label_for(goal.goal_type)
        decision["goal_projection"] = snapshot.get("active_goal_projection")
        decision["calendar_context"] = calendar_context
        decision["snapshot_summary"] = snapshot

        message_payload = _fallback_message_payload(goal, decision)
        system_prompt, user_prompt = build_telegram_prompt(
            user=user,
            goal=goal,
            decision_payload=decision,
            running_memory=running_memory,
        )
        message_result = generate_structured_payload(
            llm_client=self.llm_client,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema=TelegramMessageSchema,
            normalize=_normalize_message_payload,
            unavailable_message="Telegram drafting model unavailable",
        )
        if message_result.warning:
            decision["message_warning"] = message_result.warning
        else:
            llm_message_payload = message_result.payload
            if llm_message_payload["message_title"]:
                message_payload["message_title"] = llm_message_payload["message_title"]
            if llm_message_payload["message_body"]:
                message_payload["message_body"] = llm_message_payload["message_body"]

        decision.update(message_payload)
        decision["email_subject"] = message_payload["message_title"]
        decision["email_body"] = message_payload["message_body"]
        decision_date = _latest_reference_date(activities_df, health_df)
        stored = repository.store_coaching_decision(
            session=session,
            user_id=user.id,
            goal_id=goal.id,
            decision_type=decision_type,
            decision_date=decision_date,
            summary=str(decision.get("summary", "")),
            risk_level=str(decision.get("risk_level", "moderate")),
            payload_json=json.dumps(decision, default=str),
            email_subject=message_payload["message_title"],
            email_body=message_payload["message_body"],
        )
        repository.store_llm_memory(
            session=session,
            user_id=user.id,
            context_summary=json.dumps(snapshot, default=str),
            recommendations=json.dumps(decision, default=str),
            fatigue_flag=bool(snapshot["fatigue"]["level"] == "high"),
            confidence_score=float(decision.get("confidence", snapshot["prediction"]["confidence"])),
        )
        try:
            memory_entry = build_memory_entry_from_decision(decision_type, str(decision_date), decision)
            update_running_memory(entry=memory_entry)
        except Exception:
            pass

        delivery_status = "not_sent"
        delivery_message = ""
        if send_message:
            try:
                delivery_status, delivery_message = self.telegram_service.send(
                    title=message_payload["message_title"],
                    body=message_payload["message_body"],
                    recipient=recipient,
                )
            except Exception as exc:
                delivery_status = "failed"
                delivery_message = str(exc)

            repository.store_email_delivery(
                session=session,
                user_id=user.id,
                coaching_decision_id=stored.id,
                recipient=(recipient or self.telegram_service.default_recipient()),
                subject=message_payload["message_title"],
                status=delivery_status,
                provider_message=delivery_message,
            )

        decision["coaching_decision_id"] = stored.id
        decision["message_status"] = delivery_status
        decision["message_status_message"] = delivery_message
        decision["email_status"] = delivery_status
        decision["email_status_message"] = delivery_message
        return decision
