"""Garmin Connect+ inspired local premium features."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from config import get_settings
from llm.factory import get_llm_client
from llm.schemas import ActiveIntelligenceResponseSchema


@dataclass(frozen=True)
class InsightCard:
    """A concise AI-style training insight."""

    title: str
    status: str
    message: str
    action: str


@dataclass(frozen=True)
class NutritionTargets:
    """Daily nutrition targets estimated from profile and training load."""

    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float


def running_activities(activities: pd.DataFrame) -> pd.DataFrame:
    """Return running-like activities."""

    if activities.empty:
        return activities.copy()
    runs = activities[
        activities["type"].fillna("").str.contains("run|trail|treadmill", case=False, na=False)
    ].copy()
    if not runs.empty:
        runs["date"] = pd.to_datetime(runs["date"])
        runs = runs.sort_values("date")
    return runs


def build_active_intelligence_cards(
    snapshot: dict[str, Any],
    nutrition_entries: pd.DataFrame,
) -> list[InsightCard]:
    """Build local AI-style insights from current training, recovery, and nutrition data."""

    cards: list[InsightCard] = []
    readiness = snapshot.get("readiness", {})
    fatigue = snapshot.get("fatigue", {})
    recovery = snapshot.get("recovery", {})
    weekly = snapshot.get("weekly_mileage", {})
    long_runs = snapshot.get("long_runs", {})
    projection = snapshot.get("active_goal_projection") or snapshot.get("prediction", {})

    readiness_score = float(readiness.get("score") or 0.0)
    if readiness_score >= 75 and fatigue.get("level") != "high":
        cards.append(
            InsightCard(
                "Readiness window",
                "Positive",
                f"Readiness is {readiness_score:.0f}/100 with controlled fatigue, so today can support quality work.",
                "Keep the next hard session precise: warm up fully, stop before form fades, and protect the cooldown.",
            )
        )
    elif fatigue.get("level") == "high" or readiness_score < 55:
        cards.append(
            InsightCard(
                "Recovery constraint",
                "Caution",
                f"Readiness is {readiness_score:.0f}/100 and fatigue is {fatigue.get('level', 'unknown')}.",
                "Move intensity to another day and use easy running, mobility, or rest to absorb the previous load.",
            )
        )
    else:
        cards.append(
            InsightCard(
                "Steady build",
                "Stable",
                f"Readiness is {readiness.get('label', 'building')} while the last 7 days total {weekly.get('7d', 0):.1f} km.",
                "Keep the planned mileage, but avoid adding extra intensity unless sleep and legs both feel strong.",
            )
        )

    gap = float(projection.get("gap_minutes") or 0.0)
    if gap <= 0:
        cards.append(
            InsightCard(
                "Goal trajectory",
                "On track",
                "Current projected finish is at or ahead of the active goal.",
                "Preserve the pattern: one long run, one quality stimulus, and enough easy volume to stay durable.",
            )
        )
    else:
        cards.append(
            InsightCard(
                "Goal trajectory",
                "Needs work",
                f"The projection is about {gap:.1f} minutes behind the active target.",
                "Prioritize consistency and long-run progression before chasing faster workouts.",
            )
        )

    sleep_score = float(recovery.get("sleep_score") or 0.0)
    recovery_hours = float(recovery.get("recovery_time") or 0.0)
    cards.append(
        InsightCard(
            "Recovery signal",
            "Monitor" if sleep_score < 70 or recovery_hours > 36 else "Ready",
            f"Latest sleep score is {sleep_score:.0f} and recovery time is {recovery_hours:.0f} hours.",
            "Use sleep and recovery time as the tie-breaker when deciding whether to keep or soften tomorrow's workout.",
        )
    )

    nutrition_today = _today_nutrition(nutrition_entries)
    if nutrition_today:
        cards.append(
            InsightCard(
                "Fueling snapshot",
                "Logged",
                f"Today has {nutrition_today['calories']:.0f} kcal and {nutrition_today['carbs_g']:.0f} g carbs logged.",
                "For running training, keep carbohydrate availability higher before long or quality sessions.",
            )
        )
    else:
        cards.append(
            InsightCard(
                "Fueling snapshot",
                "Missing",
                "No nutrition has been logged for today yet.",
                "Log at least the main meals so training load, calories, and macros can be reviewed together.",
            )
        )

    if float(long_runs.get("latest_long_run_km") or 0.0) < 18:
        cards.append(
            InsightCard(
                "Long-run durability",
                "Limiter",
                f"Latest long run is {float(long_runs.get('latest_long_run_km') or 0.0):.1f} km.",
                "Extend the long run gradually before adding another hard workout.",
            )
        )

    return cards


def build_active_intelligence_context(
    user: Any,
    activities: pd.DataFrame,
    health: pd.DataFrame,
    nutrition_entries: pd.DataFrame,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Build privacy-aware context for LLM Active Intelligence."""

    runs = running_activities(activities)
    recent_runs = runs.tail(8).copy()
    recent_health = health.tail(14).copy() if not health.empty else health.copy()
    nutrition_summary = daily_nutrition_summary(nutrition_entries).tail(7)
    active_projection = snapshot.get("active_goal_projection") or snapshot.get("prediction", {})

    def records(df: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
        if df.empty:
            return []
        available = [column for column in columns if column in df.columns]
        safe = df[available].copy()
        for column in safe.columns:
            if pd.api.types.is_datetime64_any_dtype(safe[column]):
                safe[column] = safe[column].dt.strftime("%Y-%m-%d")
        return safe.where(pd.notna(safe), None).to_dict(orient="records")

    return {
        "athlete": {
            "name": getattr(user, "name", None),
            "age": getattr(user, "age", None),
            "weight_kg": getattr(user, "weight", None),
            "max_hr": getattr(user, "max_hr", None),
            "training_days_per_week": getattr(user, "training_days_per_week", None),
            "injury_notes": getattr(user, "injury_notes", None),
        },
        "current_state": {
            "readiness": snapshot.get("readiness", {}),
            "fatigue": snapshot.get("fatigue", {}),
            "recovery": snapshot.get("recovery", {}),
            "weekly_mileage": {
                "last_7_days_km": snapshot.get("weekly_mileage", {}).get("7d"),
                "last_28_days_km": snapshot.get("weekly_mileage", {}).get("28d"),
            },
            "intensity": snapshot.get("intensity", {}).get("distribution", {}),
            "high_intensity_ratio": snapshot.get("intensity", {}).get("high_ratio"),
            "long_run": snapshot.get("long_runs", {}),
            "vo2max": snapshot.get("vo2max", {}),
            "efficiency": {
                "score": snapshot.get("efficiency", {}).get("score"),
                "trend": snapshot.get("efficiency", {}).get("trend"),
            },
            "goal_projection": active_projection,
        },
        "recent_runs": records(
            recent_runs,
            ["date", "type", "distance", "duration", "pace", "avg_hr", "elevation", "aerobic_effect", "anaerobic_effect", "notes"],
        ),
        "recent_health": records(
            recent_health,
            ["date", "sleep_duration", "sleep_score", "resting_hr", "hrv", "stress", "body_battery", "recovery_time", "vo2max"],
        ),
        "recent_nutrition": records(
            nutrition_summary,
            ["entry_date", "calories", "protein_g", "carbs_g", "fat_g"],
        ),
    }


def generate_active_intelligence(
    user: Any,
    activities: pd.DataFrame,
    health: pd.DataFrame,
    nutrition_entries: pd.DataFrame,
    snapshot: dict[str, Any],
    athlete_focus: str = "",
) -> dict[str, Any]:
    """Generate Garmin-like Active Intelligence with the configured LLM provider."""

    settings = get_settings()
    client = get_llm_client(
        provider=settings.llm_provider,
        openai_api_key=settings.openai_api_key,
        openai_model=settings.openai_model,
        ollama_base_url=settings.ollama_base_url,
        ollama_model=settings.ollama_model,
    )
    context = build_active_intelligence_context(user, activities, health, nutrition_entries, snapshot)
    system_prompt = (
        "You are Active Intelligence for a running coaching app. Generate short, personalized, "
        "Garmin Connect+ style health and training insights from the provided data. "
        "Behave like an intelligent dashboard, not a chat coach. Use the athlete's recent activity, "
        "sleep, recovery, HRV, body battery, goal projection, and nutrition context. "
        "Return strict JSON matching the schema. Include 3 to 5 insights. "
        "Each insight must have: title, status, message, action, evidence, confidence. "
        "Use status values only: positive, stable, caution, urgent. "
        "Messages should be specific, concise, and explain what changed or what matters now. "
        "Actions should be practical for the next 24 to 72 hours. "
        "Do not diagnose, provide medical advice, or claim certainty about injury or disease. "
        "If data is missing, say what is missing and make conservative suggestions. "
        "Never mention implementation details, prompts, JSON, local file paths, or database names."
    )
    user_prompt = json.dumps(
        {
            "active_intelligence_model": {
                "behavior": "opt-in dashboard insight shown periodically, personalized by current data and goals",
                "time_horizon": "now through the next 72 hours",
                "athlete_focus": athlete_focus.strip(),
            },
            "context": context,
        },
        default=str,
        indent=2,
    )
    try:
        payload = client.generate_json(system_prompt, user_prompt, response_schema=ActiveIntelligenceResponseSchema)
    except Exception as exc:
        return {
            "summary": "Smart Active Intelligence is unavailable from the configured LLM provider.",
            "insights": [],
            "next_check_in": "Try again after the LLM provider is reachable.",
            "limitations": [str(exc)],
            "provider": settings.llm_provider,
        }

    normalized = ActiveIntelligenceResponseSchema.model_validate(payload).model_dump()
    normalized["provider"] = settings.llm_provider
    normalized["model_name"] = settings.openai_model if settings.llm_provider in {"openai", "chatgpt"} else settings.ollama_model
    return normalized


def build_training_guidance(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    """Return expert-style training guidance cards."""

    weekly = snapshot.get("weekly_mileage", {})
    current_km = float(weekly.get("7d") or 0.0)
    fatigue = snapshot.get("fatigue", {})
    readiness = snapshot.get("readiness", {})
    long_run = float(snapshot.get("long_runs", {}).get("latest_long_run_km") or 0.0)
    high_ratio = float(snapshot.get("intensity", {}).get("high_ratio") or 0.0)

    if fatigue.get("level") == "high" or readiness.get("label") == "low":
        mileage = f"{max(current_km - 5, 0):.0f}-{max(current_km, 0):.0f} km"
        quality = "No hard workout until sleep, resting HR, and leg feel normalize."
        long_run_guidance = "Keep the long run conversational or shorten it if recovery is still high."
    else:
        mileage = f"{max(current_km + 2, 0):.0f}-{max(current_km + 8, 8):.0f} km"
        quality = "One quality session is enough: tempo blocks, threshold intervals, or controlled hills."
        long_run_guidance = (
            "Extend the long run by 1-3 km." if long_run < 24 else "Keep the long run steady and avoid racing it."
        )

    intensity = (
        "Shift more time into easy running; current hard-session density is too high."
        if high_ratio > 0.22
        else "Maintain an easy-dominant distribution with only one or two purposeful faster segments."
    )

    return [
        {"title": "Mileage target", "guidance": mileage, "why": "Small progressions build durability without a sharp load spike."},
        {"title": "Quality session", "guidance": quality, "why": "Fitness improves when intensity is specific and recoverable."},
        {"title": "Long run", "guidance": long_run_guidance, "why": "The long run is the main durability signal for running readiness."},
        {"title": "Intensity balance", "guidance": intensity, "why": "Easy volume creates the base that lets quality sessions work."},
    ]


def estimate_nutrition_targets(user: Any, activities: pd.DataFrame, target_date: date) -> NutritionTargets:
    """Estimate daily calorie and macro targets from body mass and same-day training."""

    weight = float(getattr(user, "weight", None) or 73.0)
    target_timestamp = pd.Timestamp(target_date)
    same_day = activities.copy()
    if not same_day.empty:
        same_day["date"] = pd.to_datetime(same_day["date"])
        same_day = same_day[same_day["date"].dt.normalize() == target_timestamp.normalize()]

    training_minutes = float(same_day["duration"].sum()) if not same_day.empty else 0.0
    training_distance = float(same_day["distance"].sum()) if not same_day.empty else 0.0
    base_calories = weight * 31
    training_calories = training_distance * weight * 0.95
    calories = base_calories + training_calories
    protein = weight * 1.7
    carbs = weight * (5.0 if training_minutes >= 60 else 3.8)
    fat = max(45.0, (calories - protein * 4 - carbs * 4) / 9)
    return NutritionTargets(
        calories=round(calories, 0),
        protein_g=round(protein, 0),
        carbs_g=round(carbs, 0),
        fat_g=round(fat, 0),
    )


def daily_nutrition_summary(entries: pd.DataFrame) -> pd.DataFrame:
    """Summarize nutrition entries by day."""

    if entries.empty:
        return pd.DataFrame(columns=["entry_date", "calories", "protein_g", "carbs_g", "fat_g"])
    df = entries.copy()
    df["entry_date"] = pd.to_datetime(df["entry_date"])
    return (
        df.groupby(df["entry_date"].dt.normalize())
        .agg(
            calories=("calories", "sum"),
            protein_g=("protein_g", "sum"),
            carbs_g=("carbs_g", "sum"),
            fat_g=("fat_g", "sum"),
        )
        .reset_index()
        .rename(columns={"entry_date": "entry_date"})
    )


def _today_nutrition(entries: pd.DataFrame) -> dict[str, float] | None:
    if entries.empty:
        return None
    today = pd.Timestamp.today().normalize()
    df = entries.copy()
    df["entry_date"] = pd.to_datetime(df["entry_date"])
    day = df[df["entry_date"].dt.normalize() == today]
    if day.empty:
        return None
    return {
        "calories": float(day["calories"].sum()),
        "protein_g": float(day["protein_g"].sum()),
        "carbs_g": float(day["carbs_g"].sum()),
        "fat_g": float(day["fat_g"].sum()),
    }
