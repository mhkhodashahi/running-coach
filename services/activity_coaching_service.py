"""Per-activity LLM coach analysis."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

import pandas as pd
from pydantic import ValidationError

from config import Settings, get_settings
from db import repository
from db.models import ActivityEffort
from db.session import session_scope
from llm.factory import get_llm_client
from llm.schemas import ActivityCoachInsightSchema, CoachOpinionV2, CoachOpinionV23, OpinionDraftV23
from metrics import get_daily_snapshot
from services.coach_facts import IntentDecision, build_data_notes, build_facts, detect_intent
from services.coach_opinion import assemble_opinion_v23, load_opinion, opinion_rule_errors
from services.coaching_prompts import ACTIVITY_OPINION_V24_SYSTEM_PROMPT
from services.goal_service import GoalService
from services.running_coach_memory import (
    build_memory_entry_from_activity,
    load_running_memory,
    running_memory_block,
    update_running_memory,
)
from utils.formatting import format_pace_short

PROMPT_VERSION = "opinion-v2.4"


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

    def _prepare(self, session: Any, user: Any, activity_id: int) -> tuple[dict[str, Any], str, str | None]:
        activity = repository.get_activity(session, activity_id=activity_id, user_id=user.id)
        if activity is None:
            raise ValueError(f"Unknown activity id: {activity_id}")
        activities = repository.activities_dataframe(session, user.id)
        health = repository.health_metrics_dataframe(session, user.id)
        track_points = repository.track_points_dataframe(session, activity.id)
        laps = repository.activity_laps_dataframe(session, activity.id)
        allowed = can_generate_activity_coach_opinion(activity=activity, track_points=track_points, laps=laps)
        if not allowed.allowed:
            raise ValueError(allowed.reason)
        snapshot = get_daily_snapshot(activity.date, database=self.settings.db_path, user_id=user.id,
                                      timezone=self.settings.local_timezone,
                                      sleep_goal_hours=self.settings.sleep_goal_hours,
                                      hr_zones=self.settings.hr_zones)
        compact = _opinion_metrics_snapshot(snapshot, activity.id)
        context = build_activity_coaching_context(
            user=user, goal=self.goal_service.ensure_active_goal(session, user), activity=activity,
            activities_df=activities, health_df=health, track_points=track_points, laps=laps,
            snapshot=compact, hr_zones=self.settings.hr_zones,
        )
        rating = session.get(ActivityEffort, activity.id)
        context["effort_rpe"] = rating.rpe if rating else None
        activity_session = next((item for item in snapshot.sessions if item.activity_id == activity.id), None)
        context["effort_low_zone_share"] = (sum(zone.percent.value or 0 for zone in activity_session.zones
                                                if zone.name.startswith(("Below Z1", "Z1", "Z2")))
                                            if activity_session else None)
        facts = build_facts(activity.id, context)
        decision = detect_intent(facts, context["planned_intent"])
        if decision is None:
            raise ValueError("Cannot detect session intent without enough HR-zone evidence; sync activity detail first.")
        context["facts_pack"] = facts
        context["prompt_version"] = PROMPT_VERSION
        context["detected_intent"] = decision.intent
        context["intent_fact_ids"] = list(decision.fact_ids)
        context["data_notes"] = build_data_notes(laps.to_dict(orient="records"),
                                                 track_points.to_dict(orient="records"), activity.distance)
        return context, str(activity.date), getattr(activity, "activity_name", None)

    def _request_opinion(self, context: dict[str, Any], running_memory: str | None) -> tuple[CoachOpinionV23, str | None]:
        system_prompt, user_prompt = build_activity_coaching_prompt(context, running_memory)
        facts = context["facts_pack"]
        decision = IntentDecision(context["detected_intent"], tuple(context["intent_fact_ids"]))
        for attempt in range(2):
            try:
                payload = self.llm_client.generate_json(system_prompt, user_prompt, response_schema=OpinionDraftV23)
            except Exception as exc:
                raise RuntimeError(f"Activity coaching model unavailable: {exc}") from exc
            try:
                draft = OpinionDraftV23.model_validate(payload)
                opinion = assemble_opinion_v23(draft, facts, decision, context["planned_intent"], context["data_notes"])
                rule_errors = opinion_rule_errors(opinion, context)
                if rule_errors:
                    raise ValueError("; ".join(rule_errors))
                return opinion, None
            except (ValidationError, ValueError) as exc:
                if attempt:
                    raise RuntimeError(f"Coach opinion validation failed after retry: {exc}") from exc
                user_prompt += f"\nValidation errors: {exc}. Correct the cited facts and return the draft JSON only."
        raise RuntimeError("Coach opinion validation failed after retry")

    def _save(self, session: Any, user_id: int, activity_id: int, opinion: CoachOpinionV2,
              context: dict[str, Any], notes: str | None, regenerate: bool) -> None:
        existing = repository.get_activity_coaching_insight(session, activity_id=activity_id, user_id=user_id)
        if existing is not None and not regenerate:
            raise RuntimeError("An opinion was saved while generation was running; use Regenerate explicitly.")
        repository.upsert_activity_coaching_insight(
            session, user_id=user_id, activity_id=activity_id, summary=opinion.assessment,
            payload_json=opinion.model_dump_json(), prompt_context_json=json.dumps(context, default=_json_default),
            model_provider=self.settings.llm_provider, model_name=_model_name(self.settings),
            schema_version="2", prompt_version=PROMPT_VERSION, validation_notes=notes,
            archive_existing=regenerate,
        )

    def generate(self, session: Any, *, user: Any, activity_id: int, regenerate: bool = False) -> dict[str, Any]:
        existing = repository.get_activity_coaching_insight(session, activity_id=activity_id, user_id=user.id)
        if existing is not None and not regenerate:
            return load_opinion(existing).model_dump()
        context, activity_day, activity_name = self._prepare(session, user, activity_id)
        opinion, notes = self._request_opinion(context, load_running_memory())
        self._save(session, user.id, activity_id, opinion, context, notes, regenerate)
        _update_activity_memory(activity_day, activity_name, opinion)
        return opinion.model_dump()

    def generate_for_activity(self, *, user_id: int, activity_id: int, regenerate: bool = False) -> dict[str, Any]:
        """Generate only on an explicit call, outside a long-running database transaction."""
        with session_scope() as session:
            user = repository.get_or_create_default_user(session, user_id)
            existing = repository.get_activity_coaching_insight(session, activity_id=activity_id, user_id=user_id)
            if existing is not None and not regenerate:
                return load_opinion(existing).model_dump()
            context, activity_day, activity_name = self._prepare(session, user, activity_id)
        opinion, notes = self._request_opinion(context, load_running_memory())
        with session_scope() as session:
            self._save(session, user_id, activity_id, opinion, context, notes, regenerate)
        _update_activity_memory(activity_day, activity_name, opinion)
        return opinion.model_dump()


def build_activity_coaching_prompt(context: dict[str, Any], running_memory: str | None = None) -> tuple[str, str]:
    facts = context.get("facts_pack") or build_facts(context.get("selected_activity", {}).get("id", 0), context)
    decision = context.get("detected_intent")
    if decision is None:
        detected = detect_intent(facts, context.get("planned_intent"))
        decision = detected.intent if detected else None
    prompt_input = {
        "facts": facts,
        "planned_intent": context.get("planned_intent"),
        "detected_intent": decision,
        "intent_fact_ids": context.get("intent_fact_ids", []),
        "data_notes_from_code": context.get("data_notes", []),
    }
    return ACTIVITY_OPINION_V24_SYSTEM_PROMPT, f"{running_memory_block(running_memory)}\n{json.dumps(prompt_input, default=_json_default)}"


def _opinion_metrics_snapshot(snapshot: Any, activity_id: int) -> dict[str, Any]:
    """Bound model input while retaining dated metrics and their provenance."""
    session = next((item for item in snapshot.sessions if item.activity_id == activity_id), None)
    activity_session = None
    if session is not None:
        activity_session = {
            "activity_id": session.activity_id,
            "sport": session.sport,
            "load": asdict(session.load),
            "hrmax": asdict(session.hrmax),
            "hr_zones": [{"zone": zone.name, "seconds": zone.seconds.value,
                          "percent": zone.percent.value} for zone in session.zones],
            "hr_zone_source": "metrics.session_metrics / activity_track_points.heart_rate",
            "observed_seconds": session.observed_seconds.value,
        }
    return {
        "as_of": snapshot.as_of,
        "timezone": snapshot.timezone,
        "baselines": [asdict(item) for item in snapshot.baselines],
        "current_health": dict((name, asdict(value)) for name, value in snapshot.current_health),
        "readiness": asdict(snapshot.readiness),
        "load": asdict(snapshot.load),
        "activity_session": activity_session,
        "daily_sport_loads": [{"sport": item.sport, "load_trimp": item.load.value,
                               "source": "metrics.daily_sport_loads"} for item in snapshot.sport_loads
                              if item.period == "daily" and item.load.provenance.window_end == snapshot.as_of],
    }


def _update_activity_memory(activity_day: str, activity_name: str | None, opinion: CoachOpinionV2) -> None:
    try:
        entry = build_memory_entry_from_activity(activity_day, {
            "selected_activity_name": activity_name,
            "overall_assessment": opinion.assessment,
            "what_was_good": [point.lead for point in opinion.worked],
            "mistakes_or_inefficiencies": [point.lead for point in opinion.fix],
            "training_recommendations": [item.text for item in opinion.recommendations],
            "evidence": [f"{item.metric}: {item.value}" for item in opinion.evidence],
        })
        update_running_memory(entry=entry)
    except Exception:
        pass


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
    hr_zones: tuple[tuple[str, int, int | None], ...] = (),
) -> dict[str, Any]:
    """Build a compact data context for one activity."""

    activity_payload = _activity_payload(activity)
    activity_day = activity_payload["date"]
    recent_median_pace = _recent_runs_median_pace(activities_df, activity.id)
    recent_runs = _recent_runs_context(activities_df, activity.id)
    health_payload = _health_context(health_df, activity_day)
    stream_payload = _stream_context(track_points, float(_activity_field(activity, "distance") or 0.0), hr_zones)
    lap_payload = _laps_context(laps)
    return {
        "planned_intent": _activity_field(activity, "planned_intent"),
        "recent_median_pace": _format_pace_value(recent_median_pace),
        "athlete_profile": {
            "name": getattr(user, "name", None),
            "age": getattr(user, "age", None),
            "sex": getattr(user, "gender", None),
            "weight_kg": getattr(user, "weight", None),
            "height_cm": getattr(user, "height", None),
            "max_hr": getattr(user, "max_hr", None),
            "training_days_per_week": getattr(user, "training_days_per_week", None),
            "injury_notes": getattr(user, "injury_notes", None),
        },
        "custom_heart_rate_zones": [
            {"zone": zone, "lower_bpm": lower, "upper_bpm": upper} for zone, lower, upper in hr_zones
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
        "metrics_snapshot": snapshot,
    }


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


def _stream_context(track_points: pd.DataFrame, activity_distance_km: float,
                    hr_zones: tuple[tuple[str, int, int | None], ...]) -> dict[str, Any]:
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

    if hr_zones and "heart_rate" in samples and samples["heart_rate"].notna().any():
        summary["custom_zone_distribution"] = _custom_zone_distribution(samples, hr_zones)

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


def _custom_zone_distribution(samples: pd.DataFrame, zones: tuple[tuple[str, int, int | None], ...]) -> list[dict[str, Any]]:
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
    hr["zone"] = hr["heart_rate"].apply(lambda value: _custom_zone_for_hr(value, zones))
    grouped = hr.groupby("zone", as_index=False)["sample_seconds"].sum()
    total = float(grouped["sample_seconds"].sum()) or 1.0
    grouped["minutes"] = grouped["sample_seconds"] / 60
    grouped["percent"] = grouped["sample_seconds"] / total * 100
    return [
        {"zone": str(row.zone), "minutes": round(float(row.minutes), 1), "percent": round(float(row.percent), 1)}
        for row in grouped.itertuples()
    ]


def _custom_zone_for_hr(value: float, zones: tuple[tuple[str, int, int | None], ...]) -> str:
    for zone, lower, upper in zones:
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
