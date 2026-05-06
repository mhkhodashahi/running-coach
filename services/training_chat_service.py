"""DB-backed training chat for Telegram and local assistants."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from analytics.performance import build_training_snapshot
from config import Settings, get_settings
from db import repository
from db.session import session_scope
from db.setup import init_db
from llm.factory import get_llm_client
from llm.schemas import TelegramTrainingChatSchema


@dataclass(frozen=True)
class TrainingChatReply:
    """Answer text plus lightweight metadata for callers."""

    text: str
    used_llm: bool


class TrainingChatService:
    """Answer athlete questions using local Marathon Coach database context."""

    def __init__(self, settings: Settings | None = None, llm_client: Any | None = None) -> None:
        self.settings = settings or get_settings()
        self.llm_client = llm_client or get_llm_client(
            self.settings.llm_provider,
            self.settings.openai_api_key,
            self.settings.openai_model,
            self.settings.ollama_base_url,
            self.settings.ollama_model,
        )

    def answer(self, question: str, user_id: int | None = None) -> TrainingChatReply:
        """Answer one natural-language training question."""

        question = question.strip()
        if not question:
            return TrainingChatReply("Ask me a training question, for example: how is my recovery today?", False)

        init_db()
        context = self._build_context(user_id or self.settings.default_user_id)
        system_prompt = _system_prompt()
        user_prompt = json.dumps(
            {
                "athlete_question": question,
                "training_context": context,
            },
            default=_json_default,
            indent=2,
        )

        try:
            payload = self.llm_client.generate_json(
                system_prompt,
                user_prompt,
                response_schema=TelegramTrainingChatSchema,
            )
        except Exception as exc:
            fallback = self._fallback_answer(question, context)
            return TrainingChatReply(f"{fallback}\n\nModel unavailable: {exc}", False)

        answer = str(payload.get("answer") or payload.get("explanation") or "").strip()
        evidence = [str(item).strip() for item in payload.get("evidence", []) if str(item).strip()]
        follow_up = str(payload.get("follow_up") or "").strip()

        if not answer:
            return TrainingChatReply(self._fallback_answer(question, context), False)

        parts = [answer]
        if evidence:
            parts.append("Evidence: " + "; ".join(evidence[:4]))
        if follow_up:
            parts.append(follow_up)
        return TrainingChatReply(_telegram_limit("\n\n".join(parts)), True)

    def _build_context(self, user_id: int) -> dict[str, Any]:
        with session_scope() as session:
            user = repository.get_or_create_default_user(session, user_id)
            goal = repository.get_or_create_default_goal(session, user)
            activities = repository.activities_dataframe(session, user.id)
            health = repository.health_metrics_dataframe(session, user.id)
            goals = repository.goals_dataframe(session, user.id)
            coaching = repository.coaching_decisions_dataframe(session, user.id)

        snapshot = build_training_snapshot(user, activities, health, goal)
        return {
            "today": date.today().isoformat(),
            "athlete": {
                "name": user.name,
                "age": user.age,
                "max_hr": user.max_hr,
                "training_days_per_week": user.training_days_per_week,
            },
            "active_goal": _latest_records(goals, 1),
            "snapshot": _compact_snapshot(snapshot),
            "recent_activities": _latest_records(activities, 12),
            "recent_health": _latest_records(health, 10),
            "recent_coaching_decisions": _latest_records(coaching, 3),
        }

    def _fallback_answer(self, question: str, context: dict[str, Any]) -> str:
        snapshot = context.get("snapshot", {})
        weekly = snapshot.get("weekly_mileage", {})
        readiness = snapshot.get("readiness", {})
        fatigue = snapshot.get("fatigue", {})
        recovery = snapshot.get("recovery", {})
        prediction = snapshot.get("prediction", {})
        latest_activity = (context.get("recent_activities") or [{}])[-1]
        return _telegram_limit(
            "I can read your training DB, but the LLM did not return a usable answer.\n\n"
            f"Current snapshot: readiness {readiness.get('score')} ({readiness.get('label')}), "
            f"fatigue {fatigue.get('score')} ({fatigue.get('level')}), "
            f"7-day running volume {weekly.get('7d')} km, 28-day volume {weekly.get('28d')} km. "
            f"Latest recovery: sleep score {recovery.get('sleep_score')}, HRV {recovery.get('hrv')}, "
            f"body battery {recovery.get('body_battery')}. "
            f"Active-goal prediction: {prediction.get('predicted_time_minutes', prediction.get('predicted_minutes'))} "
            f"min at {prediction.get('predicted_pace')} min/km. "
            f"Latest activity: {latest_activity.get('date')} {latest_activity.get('type')} "
            f"{latest_activity.get('distance')} km.\n\n"
            f"Question received: {question}"
        )


def _system_prompt() -> str:
    return (
        "You are Marathon Coach inside a private Telegram chat. Answer the athlete's training question using only the "
        "provided local database context. Be concise, specific, and practical. Mention actual dates and values when "
        "available. Do not invent missing workouts, health data, diagnoses, injuries, or race guarantees. If the data "
        "is insufficient, say what is missing and give a conservative next step. Return JSON with keys: answer, "
        "evidence, follow_up."
    )


def _compact_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "weekly_mileage",
        "vo2max",
        "efficiency",
        "fatigue",
        "readiness",
        "consistency",
        "long_runs",
        "intensity",
        "prediction",
        "active_goal_projection",
        "recovery",
        "goal_pace",
    ]
    compact: dict[str, Any] = {}
    for key in keys:
        value = snapshot.get(key)
        if isinstance(value, pd.DataFrame):
            continue
        if isinstance(value, dict):
            compact[key] = {inner_key: inner_value for inner_key, inner_value in value.items() if not isinstance(inner_value, pd.DataFrame)}
        else:
            compact[key] = value
    return compact


def _latest_records(df: pd.DataFrame, limit: int) -> list[dict[str, Any]]:
    if df.empty:
        return []
    date_columns = [column for column in ("date", "scan_date", "decision_date", "target_date", "created_at") if column in df.columns]
    ordered = df.copy()
    if date_columns:
        ordered = ordered.sort_values(date_columns[-1])
    records = ordered.tail(limit).to_dict(orient="records")
    return [{key: _json_default(value) for key, value in record.items()} for record in records]


def _json_default(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_default(inner_value) for key, inner_value in value.items()}
    if isinstance(value, list):
        return [_json_default(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat() if value.time().isoformat() == "00:00:00" else value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        return value.item()
    return value


def _telegram_limit(text: str, limit: int = 3900) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 24].rstrip() + "\n\n[truncated]"
