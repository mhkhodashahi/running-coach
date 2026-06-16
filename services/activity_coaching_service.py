"""Per-activity LLM coach analysis."""

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
from llm.factory import get_llm_client
from llm.schemas import ActivityCoachInsightSchema
from services.coaching_prompts import ELITE_ENDURANCE_COACH_CONTEXT
from services.goal_service import GoalService
from services.llm_workflow import generate_structured_payload
from services.running_coach_memory import (
    build_memory_entry_from_activity,
    load_running_memory,
    running_memory_block,
    update_running_memory,
)
from utils.formatting import format_pace_short

CUSTOM_HR_ZONES = [
    ("Zone 1 Recovery", 92, 109),
    ("Zone 2 Easy/Aerobic", 110, 128),
    ("Zone 3 Steady/Aerobic", 129, 146),
    ("Zone 4 Threshold", 147, 165),
    ("Zone 5 VO2max/Max", 166, None),
]


@dataclass(frozen=True)
class ActivityCoachReadiness:
    """Whether a one-time activity coach opinion can be generated."""

    allowed: bool
    reason: str = ""


def supports_activity_coach_opinion(activity_type: str | None) -> bool:
    """Return whether an activity should get a per-workout running coach opinion."""

    normalized = str(activity_type or "").lower()
    return any(keyword in normalized for keyword in ("run", "trail", "treadmill"))


def can_generate_activity_coach_opinion(
    *,
    activity: Any,
    track_points: pd.DataFrame,
    laps: pd.DataFrame,
) -> ActivityCoachReadiness:
    """Return whether available data is good enough for a one-time coach opinion."""

    if not supports_activity_coach_opinion(_activity_field(activity, "type")):
        return ActivityCoachReadiness(False, "Activity coach opinions are only available for running workouts.")
    has_detail = not track_points.empty or not laps.empty
    has_external_id = _has_value(_activity_field(activity, "external_id"))
    has_manual_context = _has_value(_activity_field(activity, "notes"))
    if has_external_id and not has_detail and not has_manual_context:
        return ActivityCoachReadiness(
            False,
            "Sync Garmin activity detail data before generating the one-time coach opinion for this run.",
        )
    return ActivityCoachReadiness(True)


def _activity_field(activity: Any, field: str) -> Any:
    if isinstance(activity, pd.Series):
        return activity.get(field)
    return getattr(activity, field, None)


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    return bool(str(value).strip())


class ActivityCoachingService:
    """Generate and persist a coach opinion for one workout."""

    def __init__(self, settings: Settings | None = None, llm_client: Any | None = None) -> None:
        self.settings = settings or get_settings()
        self.llm_client = llm_client or get_llm_client(
            self.settings.llm_provider,
            self.settings.openai_api_key,
            self.settings.openai_model,
            self.settings.ollama_base_url,
            self.settings.ollama_model,
        )
        self.goal_service = GoalService()

    def generate(self, session, *, user: Any, activity_id: int) -> dict[str, Any]:
        """Generate and store an LLM coach opinion once for one activity."""

        activity = repository.get_activity(session, activity_id=activity_id, user_id=user.id)
        if activity is None:
            raise ValueError(f"Unknown activity id: {activity_id}")
        existing = repository.get_activity_coaching_insight(session, activity_id=activity.id, user_id=user.id)
        if existing is not None:
            try:
                return json.loads(existing.payload_json)
            except json.JSONDecodeError as exc:
                raise RuntimeError("Stored activity coach opinion is not valid JSON.") from exc

        goal = self.goal_service.ensure_active_goal(session, user)
        activities = repository.activities_dataframe(session, user.id)
        health = repository.health_metrics_dataframe(session, user.id)
        track_points = repository.track_points_dataframe(session, activity.id)
        laps = repository.activity_laps_dataframe(session, activity.id)
        readiness = can_generate_activity_coach_opinion(activity=activity, track_points=track_points, laps=laps)
        if not readiness.allowed:
            raise ValueError(readiness.reason)
        snapshot = build_training_snapshot(user, activities, health, goal=goal)
        running_memory = load_running_memory()
        activity_date_text = str(activity.date)
        activity_name = getattr(activity, "activity_name", None)
        context = build_activity_coaching_context(
            user=user,
            goal=goal,
            activity=activity,
            activities_df=activities,
            health_df=health,
            track_points=track_points,
            laps=laps,
            snapshot=snapshot,
        )
        system_prompt, user_prompt = build_activity_coaching_prompt(context, running_memory=running_memory)
        result = generate_structured_payload(
            llm_client=self.llm_client,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema=ActivityCoachInsightSchema,
            normalize=normalize_activity_coach_payload,
            unavailable_message="Activity coaching model unavailable",
        )
        if result.error is not None:
            raise result.error
        normalized = result.payload
        if not normalized["overall_assessment"]:
            raise RuntimeError("The configured LLM did not return a usable activity analysis.")

        repository.upsert_activity_coaching_insight(
            session,
            user_id=user.id,
            activity_id=activity.id,
            summary=normalized["overall_assessment"],
            payload_json=json.dumps(normalized, default=_json_default),
            prompt_context_json=json.dumps(context, default=_json_default),
            model_provider=self.settings.llm_provider,
            model_name=_model_name(self.settings),
        )
        try:
            memory_entry = build_memory_entry_from_activity(
                activity_date_text,
                normalized | {"selected_activity_name": activity_name},
            )
            update_running_memory(entry=memory_entry)
        except Exception:
            pass
        return normalized

    def generate_for_activity(self, *, user_id: int, activity_id: int) -> dict[str, Any]:
        """Generate and store an activity opinion without holding a DB session during the LLM call."""

        with session_scope() as session:
            user = repository.get_or_create_default_user(session, user_id)
            activity = repository.get_activity(session, activity_id=activity_id, user_id=user.id)
            if activity is None:
                raise ValueError(f"Unknown activity id: {activity_id}")
            existing = repository.get_activity_coaching_insight(session, activity_id=activity.id, user_id=user.id)
            if existing is not None:
                try:
                    return json.loads(existing.payload_json)
                except json.JSONDecodeError as exc:
                    raise RuntimeError("Stored activity coach opinion is not valid JSON.") from exc

            goal = self.goal_service.ensure_active_goal(session, user)
            activities = repository.activities_dataframe(session, user.id)
            health = repository.health_metrics_dataframe(session, user.id)
            track_points = repository.track_points_dataframe(session, activity.id)
            laps = repository.activity_laps_dataframe(session, activity.id)
            readiness = can_generate_activity_coach_opinion(activity=activity, track_points=track_points, laps=laps)
            if not readiness.allowed:
                raise ValueError(readiness.reason)
            snapshot = build_training_snapshot(user, activities, health, goal=goal)
            running_memory = load_running_memory()
            activity_date_text = str(activity.date)
            activity_name = getattr(activity, "activity_name", None)
            context = build_activity_coaching_context(
                user=user,
                goal=goal,
                activity=activity,
                activities_df=activities,
                health_df=health,
                track_points=track_points,
                laps=laps,
                snapshot=snapshot,
            )

        system_prompt, user_prompt = build_activity_coaching_prompt(context, running_memory=running_memory)
        result = generate_structured_payload(
            llm_client=self.llm_client,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema=ActivityCoachInsightSchema,
            normalize=normalize_activity_coach_payload,
            unavailable_message="Activity coaching model unavailable",
        )
        if result.error is not None:
            raise result.error
        normalized = result.payload
        if not normalized["overall_assessment"]:
            raise RuntimeError("The configured LLM did not return a usable activity analysis.")

        with session_scope() as session:
            repository.upsert_activity_coaching_insight(
                session,
                user_id=user_id,
                activity_id=activity_id,
                summary=normalized["overall_assessment"],
                payload_json=json.dumps(normalized, default=_json_default),
                prompt_context_json=json.dumps(context, default=_json_default),
                model_provider=self.settings.llm_provider,
                model_name=_model_name(self.settings),
            )
        try:
            memory_entry = build_memory_entry_from_activity(
                activity_date_text,
                normalized | {"selected_activity_name": activity_name},
            )
            update_running_memory(entry=memory_entry)
        except Exception:
            pass
        return normalized


def build_activity_coaching_prompt(context: dict[str, Any], running_memory: str | None = None) -> tuple[str, str]:
    """Build the structured per-workout coaching prompt."""

    system_prompt = (
        f"{ELITE_ENDURANCE_COACH_CONTEXT}\n\n"
        "# Per-Workout Analysis Task\n"
        "Analyze exactly one workout using the supplied athlete profile, active goal, selected activity, "
        "recent training context, recovery metrics, lap data, and stream summaries.\n\n"
        "# Running Memory\n"
        "Use the running_memory block for durable coaching context. Prefer the selected activity and latest metrics when they conflict with older notes.\n\n"
        "# Context Engineering\n"
        "First decide what kind of workout this most likely was from selected_activity, notes, pace, HR, "
        "training effect, lap pattern, and stream_analysis. Then judge whether the execution matched that likely purpose. "
        "Use context_engineering.analysis_frame, context_engineering.data_quality, and context_engineering.key_questions "
        "to focus your reasoning. Prioritize direct evidence from selected_activity, stream_analysis, lap_analysis, "
        "same_day_or_latest_recovery, recent_running_context, and training_snapshot in that order.\n\n"
        "You must analyze every workout deeply and give honest feedback, strengths, mistakes, pacing analysis, "
        "aerobic efficiency analysis, recovery analysis, mental/performance insights, and training recommendations.\n\n"
        "Use the athlete_profile values from the user prompt as the source of truth for age, sex, weight, max HR, "
        "training availability, and injury notes. Do not use generic athlete assumptions when profile data is present.\n\n"
        "# Output Contract\n"
        "Return strict JSON only with keys: overall_assessment, what_was_good, mistakes_or_inefficiencies, "
        "pacing_analysis, aerobic_efficiency_analysis, recovery_analysis, mental_performance_insights, "
        "training_recommendations, brutally_honest_conclusion, evidence, confidence.\n"
        "what_was_good, mistakes_or_inefficiencies, training_recommendations, and evidence must be arrays of strings. "
        "confidence must be 0-100.\n\n"
        "# Coaching Rules\n"
        "- Do not blindly praise the workout.\n"
        "- Do not just repeat Garmin metrics; interpret them like a coach.\n"
        "- If the run looks too hard for an easy day, say so directly.\n"
        "- If the athlete controlled the workout well, reward that discipline.\n"
        "- Use the custom HR zones in the context, not Garmin default zones.\n"
        "- If running mechanics data is missing, say it is unavailable instead of inventing it.\n"
        "- Be specific about what to do in the next run or next 24-48 hours.\n"
        "- Keep medical language conservative and do not diagnose."
    )
    user_prompt = f"{running_memory_block(running_memory)}\n{json.dumps(context, default=_json_default, indent=2)}"
    return system_prompt, user_prompt


def build_activity_coaching_context(
    *,
    user: Any,
    goal: Any,
    activity: Any,
    activities_df: pd.DataFrame,
    health_df: pd.DataFrame,
    track_points: pd.DataFrame,
    laps: pd.DataFrame,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Build a compact data context for one activity."""

    activity_payload = _activity_payload(activity)
    activity_day = activity_payload["date"]
    recent_median_pace = _recent_runs_median_pace(activities_df, activity.id)
    recent_runs = _recent_runs_context(activities_df, activity.id)
    health_payload = _health_context(health_df, activity_day)
    stream_payload = _stream_context(track_points, float(_activity_field(activity, "distance") or 0.0))
    lap_payload = _laps_context(laps)
    return {
        "context_engineering": _context_engineering_payload(
            activity_payload=activity_payload,
            recent_runs=recent_runs,
            health_payload=health_payload,
            stream_payload=stream_payload,
            lap_payload=lap_payload,
            selected_pace=float(_activity_field(activity, "pace"))
            if _has_value(_activity_field(activity, "pace"))
            else None,
            median_pace=recent_median_pace,
        ),
        "athlete_profile": {
            "name": getattr(user, "name", None),
            "age": getattr(user, "age", None),
            "sex": getattr(user, "gender", None),
            "weight_kg": getattr(user, "weight", None),
            "height_cm": getattr(user, "height", None),
            "max_hr": getattr(user, "max_hr", None),
            "training_days_per_week": getattr(user, "training_days_per_week", None),
            "injury_notes": getattr(user, "injury_notes", None),
            "known_goals": [
                "improve aerobic base",
                "lose weight",
                "improve 5K, 10K, and half running performance",
                "build running durability while staying injury-free",
            ],
        },
        "custom_heart_rate_zones": [
            {"zone": zone, "lower_bpm": lower, "upper_bpm": upper} for zone, lower, upper in CUSTOM_HR_ZONES
        ],
        "active_goal": {
            "name": getattr(goal, "name", None),
            "goal_type": getattr(goal, "goal_type", None),
            "goal_label": GoalService.label_for(getattr(goal, "goal_type", "")),
            "target_distance_km": getattr(goal, "target_distance_km", None),
            "target_time_minutes": getattr(goal, "target_time_minutes", None),
            "target_date": getattr(goal, "target_date", None),
        },
        "selected_activity": activity_payload,
        "stream_analysis": stream_payload,
        "lap_analysis": lap_payload,
        "same_day_or_latest_recovery": health_payload,
        "recent_running_context": recent_runs,
        "training_snapshot": _compact_snapshot(snapshot),
    }


def _context_engineering_payload(
    *,
    activity_payload: dict[str, Any],
    recent_runs: dict[str, Any],
    health_payload: dict[str, Any],
    stream_payload: dict[str, Any],
    lap_payload: dict[str, Any],
    selected_pace: float | None,
    median_pace: float | None,
) -> dict[str, Any]:
    """Give the model an explicit reasoning frame for the selected workout."""

    avg_hr = activity_payload.get("avg_hr")
    median_hr = recent_runs.get("median_avg_hr")
    likely_purpose = _likely_workout_purpose(activity_payload)
    return {
        "analysis_frame": {
            "likely_workout_purpose": likely_purpose,
            "compare_against_recent_runs": bool(recent_runs),
            "use_custom_hr_zones": True,
            "judge_easy_run_discipline": likely_purpose in {"easy/aerobic", "recovery", "base run"},
            "assess_fatigue_resistance": bool(stream_payload.get("first_half") and stream_payload.get("second_half")),
            "assess_lap_execution": bool(lap_payload.get("available")),
        },
        "data_quality": {
            "has_stream_samples": bool(stream_payload.get("available")),
            "has_laps": bool(lap_payload.get("available")),
            "has_recovery_metrics": bool(health_payload),
            "has_recent_run_baseline": bool(recent_runs.get("prior_run_count")),
            "missing_mechanics": not bool(stream_payload.get("cadence_spm") or activity_payload.get("cadence_spm")),
        },
        "comparisons": {
            "pace_vs_recent_median": _pace_delta_text(selected_pace, median_pace),
            "avg_hr_vs_recent_median_bpm": round(float(avg_hr) - float(median_hr), 1)
            if avg_hr is not None and median_hr is not None
            else None,
            "stream_hr_drift_bpm": stream_payload.get("hr_drift_bpm"),
            "stream_pace_fade": stream_payload.get("pace_fade"),
        },
        "key_questions": [
            "Did this workout match its likely purpose?",
            "Was the pacing controlled or ego-driven?",
            "Did HR stay in the right custom zones for the workout purpose?",
            "Is there evidence of aerobic efficiency or HR drift?",
            "Did recovery state support this effort?",
            "What should the athlete do differently in the next similar session?",
        ],
    }


def _likely_workout_purpose(activity: dict[str, Any]) -> str:
    notes = f"{activity.get('activity_name', '')} {activity.get('notes', '')}".lower()
    activity_type = str(activity.get("type") or "").lower()
    avg_hr = activity.get("avg_hr")
    distance = float(activity.get("distance_km") or 0.0)
    if any(keyword in notes for keyword in ("recovery", "easy", "zone 2", "z2")):
        return "easy/aerobic"
    if any(keyword in notes for keyword in ("interval", "vo2", "speed", "repeat")):
        return "VO2max/speed"
    if any(keyword in notes for keyword in ("threshold", "tempo", "race pace")):
        return "threshold/tempo"
    if distance >= 16:
        return "long run"
    if "run" in activity_type and avg_hr is not None:
        if float(avg_hr) <= 128:
            return "easy/aerobic"
        if float(avg_hr) <= 146:
            return "steady/base run"
        if float(avg_hr) <= 165:
            return "threshold/tempo"
        return "VO2max/hard"
    return "general training"


def _activity_payload(activity: Any) -> dict[str, Any]:
    return {
        "id": activity.id,
        "activity_name": getattr(activity, "activity_name", None),
        "date": _json_default(activity.date),
        "type": activity.type,
        "distance_km": activity.distance,
        "duration_min": activity.duration,
        "pace": _format_pace_value(activity.pace),
        "avg_hr": activity.avg_hr,
        "max_hr": activity.max_hr,
        "cadence_spm": activity.cadence,
        "elevation_m": activity.elevation,
        "training_effect": activity.training_effect,
        "aerobic_effect": activity.aerobic_effect,
        "anaerobic_effect": activity.anaerobic_effect,
        "notes": activity.notes,
    }


def _recent_runs_context(activities: pd.DataFrame, activity_id: int) -> dict[str, Any]:
    if activities.empty:
        return {}
    runs = activities[activities["type"].fillna("").str.contains("run|trail|treadmill", case=False, na=False)].copy()
    if runs.empty:
        return {}
    runs["date"] = pd.to_datetime(runs["date"])
    selected = runs[runs["id"] == activity_id]
    selected_date = selected["date"].iloc[0] if not selected.empty else runs["date"].max()
    prior = runs[(runs["id"] != activity_id) & (runs["date"] <= selected_date)].tail(12)
    return {
        "prior_run_count": int(len(prior)),
        "median_distance_km": _float_or_none(prior["distance"].median()) if not prior.empty else None,
        "median_pace": _format_pace_value(prior["pace"].median()) if not prior.empty else None,
        "median_avg_hr": _float_or_none(prior["avg_hr"].median()) if not prior.empty else None,
        "recent_runs": [_activity_record_json(row) for row in prior.tail(6).to_dict(orient="records")],
    }


def _recent_runs_median_pace(activities: pd.DataFrame, activity_id: int) -> float | None:
    if activities.empty:
        return None
    runs = activities[activities["type"].fillna("").str.contains("run|trail|treadmill", case=False, na=False)].copy()
    if runs.empty:
        return None
    runs["date"] = pd.to_datetime(runs["date"])
    selected = runs[runs["id"] == activity_id]
    selected_date = selected["date"].iloc[0] if not selected.empty else runs["date"].max()
    prior = runs[(runs["id"] != activity_id) & (runs["date"] <= selected_date)].tail(12)
    if prior.empty:
        return None
    value = prior["pace"].median()
    return float(value) if pd.notna(value) else None


def _health_context(health: pd.DataFrame, activity_day: Any) -> dict[str, Any]:
    if health.empty:
        return {}
    rows = health.copy()
    rows["date"] = pd.to_datetime(rows["date"])
    target = pd.to_datetime(activity_day)
    rows = rows[rows["date"] <= target].sort_values("date")
    if rows.empty:
        return {}
    latest = rows.iloc[-1].to_dict()
    return _record_json(latest)


def _stream_context(track_points: pd.DataFrame, activity_distance_km: float) -> dict[str, Any]:
    if track_points.empty:
        return {"available": False, "reason": "No activity stream samples stored."}

    samples = track_points.copy()
    for column in ("pace", "heart_rate", "cadence", "distance_km", "elapsed_seconds"):
        if column in samples:
            samples[column] = pd.to_numeric(samples[column], errors="coerce")
    summary: dict[str, Any] = {"available": True, "sample_count": int(len(samples))}

    for column, output_name in (("pace", "pace"), ("heart_rate", "heart_rate"), ("cadence", "cadence_spm")):
        if column in samples and samples[column].notna().any():
            values = samples[column].dropna()
            if column == "pace":
                summary[output_name] = {
                    "avg": _format_pace_value(values.mean()),
                    "min": _format_pace_value(values.min()),
                    "max": _format_pace_value(values.max()),
                }
            else:
                summary[output_name] = {
                    "avg": round(float(values.mean()), 2),
                    "min": round(float(values.min()), 2),
                    "max": round(float(values.max()), 2),
                }

    if "heart_rate" in samples and samples["heart_rate"].notna().any():
        summary["custom_zone_distribution"] = _custom_zone_distribution(samples)

    first_half, second_half = _split_stream_halves(samples, activity_distance_km)
    if not first_half.empty and not second_half.empty:
        summary["first_half"] = _half_summary(first_half)
        summary["second_half"] = _half_summary(second_half)
        first_hr = summary["first_half"].get("avg_hr")
        second_hr = summary["second_half"].get("avg_hr")
        first_pace = summary["first_half"].get("avg_pace")
        second_pace = summary["second_half"].get("avg_pace")
        first_pace_value = _float_or_none(first_half["pace"].mean()) if "pace" in first_half else None
        second_pace_value = _float_or_none(second_half["pace"].mean()) if "pace" in second_half else None
        if first_hr is not None and second_hr is not None:
            summary["hr_drift_bpm"] = round(second_hr - first_hr, 1)
        if first_pace is not None and second_pace is not None and first_pace_value is not None and second_pace_value is not None:
            summary["pace_fade"] = _pace_delta_text_from_delta(second_pace_value - first_pace_value)
    return summary


def _split_stream_halves(samples: pd.DataFrame, activity_distance_km: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    if "distance_km" in samples and samples["distance_km"].notna().any() and activity_distance_km > 0:
        midpoint = activity_distance_km / 2
        return samples[samples["distance_km"] <= midpoint], samples[samples["distance_km"] > midpoint]
    midpoint_index = len(samples) // 2
    return samples.iloc[:midpoint_index], samples.iloc[midpoint_index:]


def _half_summary(samples: pd.DataFrame) -> dict[str, Any]:
    return {
        "avg_pace": _format_pace_value(samples["pace"].mean()) if "pace" in samples else None,
        "avg_hr": _float_or_none(samples["heart_rate"].mean()) if "heart_rate" in samples else None,
        "avg_cadence": _float_or_none(samples["cadence"].mean()) if "cadence" in samples else None,
    }


def _custom_zone_distribution(samples: pd.DataFrame) -> list[dict[str, Any]]:
    hr = samples.dropna(subset=["heart_rate"]).copy()
    if hr.empty:
        return []
    elapsed = pd.to_numeric(hr.get("elapsed_seconds"), errors="coerce")
    if elapsed.notna().sum() >= 2:
        seconds = elapsed.diff().shift(-1)
        median_step = seconds[(seconds > 0) & (seconds <= 120)].median()
        fallback_step = float(median_step) if pd.notna(median_step) else 1.0
        hr["sample_seconds"] = seconds.where((seconds > 0) & (seconds <= 300), fallback_step)
    else:
        hr["sample_seconds"] = 1.0
    hr["zone"] = hr["heart_rate"].apply(_custom_zone_for_hr)
    grouped = hr.groupby("zone", as_index=False)["sample_seconds"].sum()
    total = float(grouped["sample_seconds"].sum()) or 1.0
    grouped["minutes"] = grouped["sample_seconds"] / 60
    grouped["percent"] = grouped["sample_seconds"] / total * 100
    return [
        {"zone": str(row.zone), "minutes": round(float(row.minutes), 1), "percent": round(float(row.percent), 1)}
        for row in grouped.itertuples()
    ]


def _custom_zone_for_hr(value: float) -> str:
    for zone, lower, upper in CUSTOM_HR_ZONES:
        if value >= lower and (upper is None or value <= upper):
            return zone
    return "Below Zone 1"


def _laps_context(laps: pd.DataFrame) -> dict[str, Any]:
    if laps.empty:
        return {"available": False}
    records = []
    for row in laps.head(30).to_dict(orient="records"):
        records.append(_activity_record_json(row))
    return {"available": True, "lap_count": int(len(laps)), "laps": records}


def _compact_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    keys = ("weekly_mileage", "fatigue", "readiness", "recovery", "intensity", "efficiency", "vo2max", "prediction", "active_goal_projection")
    compact: dict[str, Any] = {}
    for key in keys:
        value = snapshot.get(key)
        if isinstance(value, dict):
            compact[key] = {
                inner_key: _format_context_value(inner_key, inner_value)
                for inner_key, inner_value in value.items()
                if not isinstance(inner_value, pd.DataFrame)
            }
        elif not isinstance(value, pd.DataFrame):
            compact[key] = _format_context_value(key, value)
    return compact


def _format_context_value(key: str, value: Any) -> Any:
    if isinstance(value, dict):
        return {inner_key: _format_context_value(inner_key, inner_value) for inner_key, inner_value in value.items()}
    if isinstance(value, list):
        return [_format_context_value(key, item) for item in value]
    if "pace" in str(key).lower():
        return _format_pace_value(value)
    return value


def normalize_activity_coach_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize common structured and local-model activity analysis responses."""

    payload = dict(payload or {})
    for container_key in ("activity_analysis", "analysis", "coach_opinion", "result", "response"):
        nested = payload.get(container_key)
        if isinstance(nested, dict):
            outer = {key: value for key, value in payload.items() if key != container_key and _has_value(value)}
            payload = nested | outer
            break
    _copy_first_present(
        payload,
        target="overall_assessment",
        aliases=("summary", "assessment", "analysis", "coach_opinion", "explanation", "response", "message"),
    )
    _copy_first_present(payload, target="what_was_good", aliases=("strengths", "positives", "what_went_well"))
    _copy_first_present(
        payload,
        target="mistakes_or_inefficiencies",
        aliases=("weaknesses", "areas_to_improve", "mistakes", "limiters"),
    )
    _copy_first_present(payload, target="training_recommendations", aliases=("recommendations", "next_steps", "actions"))
    _copy_first_present(payload, target="pacing_analysis", aliases=("pacing", "pace_analysis"))
    _copy_first_present(
        payload,
        target="aerobic_efficiency_analysis",
        aliases=("aerobic_efficiency", "efficiency_analysis"),
    )
    _copy_first_present(payload, target="recovery_analysis", aliases=("recovery",))
    _copy_first_present(payload, target="mental_performance_insights", aliases=("mental", "mindset"))
    _copy_first_present(payload, target="brutally_honest_conclusion", aliases=("conclusion", "honest_conclusion"))
    for key in ("what_was_good", "mistakes_or_inefficiencies", "training_recommendations", "evidence"):
        value = payload.get(key)
        if isinstance(value, str):
            payload[key] = [value]
        elif isinstance(value, list):
            payload[key] = [_stringify_model_value(item) for item in value if _has_value(item)]
        elif value is not None and not isinstance(value, list):
            payload[key] = [_stringify_model_value(value)]
    for key in (
        "overall_assessment",
        "pacing_analysis",
        "aerobic_efficiency_analysis",
        "recovery_analysis",
        "mental_performance_insights",
        "brutally_honest_conclusion",
    ):
        if key in payload:
            payload[key] = _stringify_model_value(payload[key])
    normalized = ActivityCoachInsightSchema(**payload).model_dump()
    return normalized


def _copy_first_present(payload: dict[str, Any], *, target: str, aliases: tuple[str, ...]) -> None:
    if _has_value(payload.get(target)):
        return
    for alias in aliases:
        value = payload.get(alias)
        if _has_value(value):
            payload[target] = value
            return


def _stringify_model_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(_stringify_model_value(item) for item in value if _has_value(item))
    if isinstance(value, dict):
        return json.dumps(value, default=_json_default, ensure_ascii=False)
    if value is None:
        return ""
    return str(value).strip()


def _model_name(settings: Settings) -> str:
    if settings.llm_provider == "openai":
        return settings.openai_model
    if settings.llm_provider == "ollama":
        return settings.ollama_model
    return ""


def _float_or_none(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if value is None:
        return None
    return round(float(value), 2)


def _format_pace_value(value: Any) -> str | None:
    numeric = _float_or_none(value)
    if numeric is None:
        return None
    return format_pace_short(numeric)


def _pace_delta_text(value: float | None, baseline: float | None) -> str | None:
    if value is None or baseline is None:
        return None
    return _pace_delta_text_from_delta(value - baseline)


def _pace_delta_text_from_delta(delta: Any) -> str | None:
    numeric = _float_or_none(delta)
    if numeric is None:
        return None
    if numeric == 0:
        return "same pace"
    label = "slower" if numeric > 0 else "faster"
    return f"{format_pace_short(abs(numeric))} {label}"


def _activity_record_json(record: dict[str, Any]) -> dict[str, Any]:
    formatted = _record_json(record)
    if "pace" in formatted:
        formatted["pace"] = _format_pace_value(record.get("pace"))
    return formatted


def _record_json(record: dict[str, Any]) -> dict[str, Any]:
    return {key: _json_default(value) for key, value in record.items()}


def _json_default(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_default(inner_value) for key, inner_value in value.items()}
    if isinstance(value, list):
        return [_json_default(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat() if value.time().isoformat() == "00:00:00" else value.isoformat()
    if isinstance(value, date):
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
