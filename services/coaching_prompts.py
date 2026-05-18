"""Prompt builders for structured coaching and Telegram generation."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import pandas as pd

from services.goal_service import GoalService


def _goal_payload(goal: Any | None) -> dict[str, Any]:
    if goal is None:
        return {}
    return {
        "name": getattr(goal, "name", ""),
        "goal_type": getattr(goal, "goal_type", ""),
        "goal_label": GoalService.label_for(getattr(goal, "goal_type", "")),
        "target_distance_km": getattr(goal, "target_distance_km", None),
        "target_time_minutes": getattr(goal, "target_time_minutes", None),
        "target_date": getattr(goal, "target_date", None),
        "priority": getattr(goal, "priority", ""),
        "notes": getattr(goal, "notes", ""),
    }


def _compact_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    weekly = snapshot.get("weekly_mileage", {})
    vo2 = snapshot.get("vo2max", {})
    efficiency = snapshot.get("efficiency", {})
    fatigue = snapshot.get("fatigue", {})
    readiness = snapshot.get("readiness", {})
    consistency = snapshot.get("consistency", {})
    long_runs = snapshot.get("long_runs", {})
    intensity = snapshot.get("intensity", {})
    recovery = snapshot.get("recovery", {})
    prediction = snapshot.get("prediction", {})
    active_goal_projection = snapshot.get("active_goal_projection") or {}
    correlations = snapshot.get("correlations", {})

    return {
        "weekly_mileage": {
            "7d_km": weekly.get("7d"),
            "28d_km": weekly.get("28d"),
        },
        "vo2max": {
            "latest": vo2.get("latest"),
            "delta": vo2.get("delta"),
            "trend": vo2.get("trend"),
        },
        "efficiency": {
            "score": efficiency.get("score"),
            "trend": efficiency.get("trend"),
        },
        "fatigue": {
            "score": fatigue.get("score"),
            "level": fatigue.get("level"),
            "reasons": fatigue.get("reasons", []),
        },
        "readiness": {
            "score": readiness.get("score"),
            "label": readiness.get("label"),
        },
        "consistency": {
            "score": consistency.get("score"),
            "active_days_28d": consistency.get("active_days"),
        },
        "long_runs": {
            "latest_long_run_km": long_runs.get("latest_long_run_km"),
        },
        "intensity": {
            "high_ratio": intensity.get("high_ratio"),
            "distribution": intensity.get("distribution"),
        },
        "recovery": {
            "sleep_duration_hours": recovery.get("sleep_duration"),
            "sleep_score": recovery.get("sleep_score"),
            "resting_hr": recovery.get("resting_hr"),
            "hrv": recovery.get("hrv"),
            "stress": recovery.get("stress"),
            "body_battery": recovery.get("body_battery"),
            "recovery_time_hours": recovery.get("recovery_time"),
            "vo2max": recovery.get("vo2max"),
        },
        "race_prediction": {
            "predicted_pace_min_per_km": prediction.get("predicted_pace"),
            "predicted_time_minutes": prediction.get("predicted_minutes"),
            "gap_minutes": prediction.get("gap_minutes"),
            "confidence": prediction.get("confidence"),
        },
        "active_goal_projection": active_goal_projection,
        "goal_pace_min_per_km": snapshot.get("goal_pace"),
        "sleep_pace_correlation": correlations.get("correlation"),
    }


def _telegram_snapshot_payload(decision_payload: dict[str, Any]) -> dict[str, Any]:
    snapshot = decision_payload.get("snapshot_summary")
    if not isinstance(snapshot, dict):
        return {}
    return _compact_snapshot(snapshot)


def _user_payload(user: Any) -> dict[str, Any]:
    return {
        "name": getattr(user, "name", None),
        "age": getattr(user, "age", None),
        "gender": getattr(user, "gender", None),
        "weight_kg": getattr(user, "weight", None),
        "height_cm": getattr(user, "height", None),
        "max_hr": getattr(user, "max_hr", None),
        "training_days_per_week": getattr(user, "training_days_per_week", None),
        "injury_notes": getattr(user, "injury_notes", None),
    }


def _activity_record(row: Any) -> dict[str, Any]:
    timestamp = pd.Timestamp(row.date)
    activity_time = timestamp.strftime("%H:%M") if (timestamp.hour or timestamp.minute or timestamp.second) else None
    return {
        "date": str(timestamp.date()),
        "time": activity_time,
        "type": row.type,
        "distance_km": round(float(row.distance), 1) if row.distance is not None else None,
        "duration_min": round(float(row.duration), 1) if row.duration is not None else None,
        "pace_min_per_km": round(float(row.pace), 2) if row.pace is not None else None,
        "avg_hr": round(float(row.avg_hr), 1) if row.avg_hr is not None else None,
        "max_hr": round(float(row.max_hr), 1) if row.max_hr is not None else None,
        "cadence": round(float(row.cadence), 1) if row.cadence is not None else None,
        "elevation_m": round(float(row.elevation), 1) if row.elevation is not None else None,
        "training_effect": round(float(row.training_effect), 1) if row.training_effect is not None else None,
        "aerobic_effect": round(float(row.aerobic_effect), 1) if row.aerobic_effect is not None else None,
        "anaerobic_effect": round(float(row.anaerobic_effect), 1) if row.anaerobic_effect is not None else None,
        "notes": row.notes,
    }


def _latest_day_activities_payload(activities_df: pd.DataFrame) -> dict[str, Any]:
    if activities_df.empty:
        return {"date": None, "activities": [], "totals": {}}

    activities = activities_df.copy()
    activities["date"] = pd.to_datetime(activities["date"])
    latest_day = activities["date"].dt.normalize().max()
    day_activities = activities[activities["date"].dt.normalize() == latest_day].sort_values("date")
    run_mask = day_activities["type"].fillna("").str.contains("run|trail|treadmill", case=False, na=False)
    return {
        "date": str(latest_day.date()),
        "activities": [_activity_record(row) for row in day_activities.itertuples()],
        "totals": {
            "activity_count": int(len(day_activities)),
            "total_distance_km": round(float(day_activities["distance"].fillna(0).sum()), 1),
            "total_duration_min": round(float(day_activities["duration"].fillna(0).sum()), 1),
            "running_distance_km": round(float(day_activities.loc[run_mask, "distance"].fillna(0).sum()), 1),
            "running_duration_min": round(float(day_activities.loc[run_mask, "duration"].fillna(0).sum()), 1),
        },
    }


def build_calendar_context(activities_df: pd.DataFrame | None = None, health_df: pd.DataFrame | None = None) -> dict[str, Any]:
    """Return explicit local date context for coaching prompts."""

    now = datetime.now().astimezone()
    today = now.date()

    latest_activity_day = None
    if activities_df is not None and not activities_df.empty:
        activities = activities_df.copy()
        activities["date"] = pd.to_datetime(activities["date"])
        latest_activity_day = activities["date"].dt.normalize().max().date()

    latest_health_day = None
    if health_df is not None and not health_df.empty:
        health = health_df.copy()
        health["date"] = pd.to_datetime(health["date"])
        latest_health_day = health["date"].dt.normalize().max().date()

    def relation(day: Any | None) -> dict[str, Any]:
        if day is None:
            return {"date": None, "is_today": False, "days_ago": None}
        days_ago = (today - day).days
        return {
            "date": day.isoformat(),
            "weekday": day.strftime("%A"),
            "human": f"{day.strftime('%A')} {day.day} {day.strftime('%B %Y')}",
            "is_today": days_ago == 0,
            "days_ago": days_ago,
        }

    return {
        "current_local_date": today.isoformat(),
        "current_local_weekday": today.strftime("%A"),
        "current_local_human": f"{today.strftime('%A')} {today.day} {today.strftime('%B %Y')}",
        "current_local_time": now.strftime("%H:%M"),
        "timezone": now.tzname(),
        "latest_activity_day": relation(latest_activity_day),
        "latest_health_day": relation(latest_health_day),
        "coaching_instruction": (
            "Use current_local_human as today's date. If latest_activity_day.is_today is true, treat the latest activity as today's completed session, "
            "not yesterday's workout. If latest_activity_day.days_ago is 1, refer to it as yesterday. Otherwise use the exact date."
        ),
    }


def _history_payload(prior_decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trimmed: list[dict[str, Any]] = []
    for item in prior_decisions[:3]:
        trimmed.append(
            {
                "decision_date": item.get("decision_date"),
                "decision_type": item.get("decision_type"),
                "summary": item.get("summary"),
                "priority": item.get("priority"),
                "risk_level": item.get("risk_level"),
            }
        )
    return trimmed


def _decision_examples(decision_type: str) -> list[dict[str, Any]]:
    if decision_type == "weekly":
        return [
            {
                "summary": "Training is moving, but fatigue is too high to justify a bigger week right now.",
                "yesterday_assessment": "Recent training load is acceptable, but recovery markers are below normal.",
                "tomorrow_recommendation": "Keep tomorrow easy or off if the legs still feel heavy.",
                "weekly_outlook": "Hold next week near current volume, keep one quality session, and protect the long run.",
                "goal_alignment": "You are still behind the active goal because recovery is limiting quality adaptation.",
                "risk_level": "moderate",
                "confidence": 61,
                "key_positives": ["Consistency is solid.", "Long run habit is in place."],
                "key_limiters": ["Recovery markers are under pressure.", "Too much intensity recently."],
                "evidence": ["Fatigue 68 (moderate)", "Sleep score 69", "High-intensity ratio 0.28"],
                "priority": "Reduce intensity before increasing mileage.",
            }
        ]
    return [
        {
            "summary": "Today should be controlled because recovery markers are not strong enough for another hard session.",
            "yesterday_assessment": "The last session added useful work, but recovery has not fully caught up yet.",
            "tomorrow_recommendation": "Run easy or cross-train lightly and reassess freshness afterward.",
            "weekly_outlook": "Stay consistent this week, but avoid stacking hard sessions.",
            "goal_alignment": "The active goal is still realistic if you protect recovery and keep consistent volume.",
            "risk_level": "high",
            "confidence": 57,
            "key_positives": ["Recent mileage is steady."],
            "key_limiters": ["Sleep and readiness are weak today.", "Recovery time is elevated."],
            "evidence": ["Readiness 48 (low)", "Recovery time 32 h", "7-day mileage 42.0 km"],
            "priority": "Do not force intensity today.",
        }
    ]


def build_decision_prompt(
    *,
    decision_type: str,
    user: Any,
    goal: Any | None,
    snapshot: dict[str, Any],
    activities_df: pd.DataFrame,
    prior_decisions: list[dict[str, Any]],
    athlete_note: str,
    rules: list[str],
) -> tuple[str, str]:
    compact_snapshot = _compact_snapshot(snapshot)
    user_payload = _user_payload(user)
    latest_day_activities = _latest_day_activities_payload(activities_df)
    calendar_context = build_calendar_context(activities_df)
    history_payload = _history_payload(prior_decisions)
    examples = _decision_examples(decision_type)
    system_prompt = (
        "# Identity\n"
        "You are Running Coach, an AI endurance running coach focused on performance, consistency, and runner safety.\n"
        "This is part of a continuous coaching relationship. Use prior coaching context when it is relevant.\n"
        "Respond like an experienced coach, not like a generic report generator.\n\n"
        "# Task\n"
        f"Produce one structured {decision_type} coaching decision using only the supplied goal, athlete profile, training history, metrics, and note.\n\n"
        "# Coaching Responsibilities\n"
        "Use the supplied calendar_context to understand today's exact date and weekday before writing the decision.\n"
        "If the latest activity happened today, describe it as today's run/session. Do not call it yesterday.\n"
        "If the latest activity happened yesterday, describe it as yesterday. Otherwise use the exact activity date.\n"
        "Before writing the decision, inspect every activity completed on the latest activity day and the latest recovery metrics. The decision must be based on what happened, not generic training advice.\n"
        "Use specific available data points from latest_day_activities and analytics, especially all same-day activity types, total day distance/duration, run pace/HR, sleep score/duration, body battery, HRV, resting HR, recovery time, weekly mileage, intensity distribution, and active-goal gap.\n"
        "If a key metric is unavailable, do not invent it; use another available metric or state that it is unavailable.\n"
        "1. Monitor strain and risk patterns, including:\n"
        "   - sudden spikes in distance, pace, duration, or intensity\n"
        "   - long runs far above recent norms\n"
        "   - high intensity with weak recovery\n"
        "   - multiple hard efforts without enough easy running or recovery\n"
        "   - training that drifts away from the active goal requirements\n"
        "2. When risk is detected:\n"
        "   - clearly say the athlete may be overdoing it\n"
        "   - explain why in simple human language\n"
        "   - recommend slowing down, resting, or reducing load before prescribing more work\n"
        "   - emphasize long-term progress over short-term ego\n"
        "3. Medical awareness and escalation:\n"
        "   - do not diagnose\n"
        "   - stay calm and non-alarming\n"
        "   - only recommend medical evaluation if the athlete note or context suggests serious warning signs such as chest discomfort, dizziness, or persistent abnormal fatigue\n"
        "4. Communication rules:\n"
        "   - address the athlete by name when a name is available\n"
        "   - prioritize the active goal over generic marathon advice\n"
        "   - use only provided data; if data is missing, say it is unavailable instead of guessing\n"
        "   - keep advice actionable and conservative when signals conflict\n"
        "   - explain why the recommendation is better than simply pushing harder\n\n"
        "# Output Contract\n"
        "- Return strict JSON only.\n"
        "- Required keys: summary, yesterday_assessment, tomorrow_recommendation, weekly_outlook, goal_alignment, risk_level, confidence, key_positives, key_limiters, evidence, priority.\n"
        "- risk_level must be one of: low, moderate, high.\n"
        "- confidence must be a number from 0 to 100.\n"
        "- key_positives, key_limiters, and evidence must each be arrays of short strings.\n"
        "- evidence must include at least 4 concrete data points when available, not generic statements.\n"
        "- yesterday_assessment must mention all activities from the latest activity day and the latest sleep/recovery state when available.\n"
        "- tomorrow_recommendation must explicitly connect the recommendation to the evidence.\n"
        "- Keep each field concise and specific.\n\n"
        "# Style\n"
        "- Calm, direct, coach-like.\n"
        "- No hype, no fear-based language, no medical claims, no motivational filler.\n"
        "- Focus on sustainable progress and safety.\n\n"
        "# Primary Goal\n"
        "Help the athlete improve sustainably while actively reducing injury and overtraining risk.\n"
        "If the data is ambiguous, it is better to be slightly conservative than recklessly aggressive.\n\n"
        "# Examples\n"
        f"<example_output>{json.dumps(examples, ensure_ascii=True)}</example_output>"
    )
    user_prompt = (
        "# Decision Context\n"
        f"<decision_type>{decision_type}</decision_type>\n"
        f"<athlete_profile>{json.dumps(user_payload, default=str, ensure_ascii=True)}</athlete_profile>\n"
        f"<calendar_context>{json.dumps(calendar_context, default=str, ensure_ascii=True)}</calendar_context>\n"
        f"<active_goal>{json.dumps(_goal_payload(goal), default=str, ensure_ascii=True)}</active_goal>\n"
        f"<latest_day_activities>{json.dumps(latest_day_activities, default=str, ensure_ascii=True)}</latest_day_activities>\n"
        f"<rule_recommendations>{json.dumps(rules, default=str, ensure_ascii=True)}</rule_recommendations>\n"
        f"<prior_coaching_context>{json.dumps(history_payload, default=str, ensure_ascii=True)}</prior_coaching_context>\n"
        f"<athlete_note>{athlete_note.strip() or 'None provided.'}</athlete_note>\n"
        f"<analytics>{json.dumps(compact_snapshot, default=str, ensure_ascii=True)}</analytics>"
    )
    return system_prompt, user_prompt


def build_telegram_prompt(
    *,
    user: Any | None = None,
    goal: Any | None,
    decision_payload: dict[str, Any],
) -> tuple[str, str]:
    athlete_name = getattr(user, "name", None) if user is not None else None
    compact_payload = {
        "summary": decision_payload.get("summary"),
        "yesterday_assessment": decision_payload.get("yesterday_assessment"),
        "tomorrow_recommendation": decision_payload.get("tomorrow_recommendation"),
        "weekly_outlook": decision_payload.get("weekly_outlook"),
        "goal_alignment": decision_payload.get("goal_alignment"),
        "risk_level": decision_payload.get("risk_level"),
        "confidence": decision_payload.get("confidence"),
        "priority": decision_payload.get("priority"),
        "evidence": decision_payload.get("evidence"),
        "key_positives": decision_payload.get("key_positives"),
        "key_limiters": decision_payload.get("key_limiters"),
        "readiness_assessment": decision_payload.get("readiness_assessment"),
        "training_effectiveness": decision_payload.get("training_effectiveness"),
        "calendar_context": decision_payload.get("calendar_context"),
        "snapshot_summary": _telegram_snapshot_payload(decision_payload),
    }
    system_prompt = (
        "# Identity\n"
        "You are a thoughtful running coach writing a Telegram update to one athlete.\n\n"
        "# Task\n"
        "Turn the coaching decision into a concrete Telegram message grounded in the athlete's actual latest data.\n"
        "The athlete is unhappy with generic messages. Be specific about what they did and what their body signals show.\n\n"
        "# Evidence Requirements\n"
        "- Use calendar_context to understand today's exact date and whether the latest activity was today, yesterday, or earlier.\n"
        "- If the latest activity was today, call it today's run/session instead of yesterday's.\n"
        "- Mention the latest activity details when available: type, distance, duration, pace, average HR, and training effect.\n"
        "- Mention sleep/recovery when available: sleep duration, sleep score, recovery time, body battery, HRV, resting HR, stress.\n"
        "- Mention training context when available: 7-day mileage, 28-day mileage, intensity balance, fatigue/readiness, long-run status.\n"
        "- Mention goal impact: whether this supports or limits the active goal, and why.\n"
        "- If a metric is missing, skip it; do not invent numbers.\n"
        "- Prefer exact values from coaching_decision.evidence and snapshot_summary over vague phrases.\n\n"
        "# Output Contract\n"
        "- Return strict JSON only.\n"
        "- Required keys: message_title, message_body.\n"
        "- message_title must be short and informative.\n"
        "- message_body must be plain text only.\n\n"
        "# Style\n"
        "- Sound like a real human coach, not a dashboard or report.\n"
        "- Calm, direct, warm, and specific.\n"
        "- Start with the main point in natural language, then support it with actual data.\n"
        "- Keep it compact enough for Telegram.\n"
        "- Use 3 to 5 short paragraphs.\n"
        "- Do not use markdown tables.\n"
        "- Light labels are allowed if they improve clarity, for example: Yesterday, Recovery, Training, Next step.\n"
        "- Include 4 to 8 concrete metrics if available.\n"
        "- Do not dump every field mechanically; explain what the numbers mean.\n"
        "- Avoid sounding clinical, robotic, or overly formal.\n"
        "- End with one clear next step.\n"
        "- If the athlete name is available, you may address them naturally once.\n"
    )
    user_prompt = (
        "# Delivery Context\n"
        f"<athlete_name>{athlete_name or ''}</athlete_name>\n"
        f"<active_goal>{json.dumps(_goal_payload(goal), default=str, ensure_ascii=True)}</active_goal>\n"
        f"<coaching_decision>{json.dumps(compact_payload, default=str, ensure_ascii=True)}</coaching_decision>"
    )
    return system_prompt, user_prompt
