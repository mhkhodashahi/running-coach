"""Hybrid coaching engine combining rules and LLM output."""

from __future__ import annotations

from typing import Any

from config import get_settings


def build_rule_recommendations(snapshot: dict[str, Any]) -> list[str]:
    """Apply deterministic coaching checks before any LLM call."""

    settings = get_settings()
    rules: list[str] = []
    recovery = snapshot.get("recovery", {})
    fatigue = snapshot.get("fatigue", {})
    intensity = snapshot.get("intensity", {})
    long_runs = snapshot.get("long_runs", {})

    if recovery.get("recovery_time", 0) > settings.recovery_threshold_hours:
        rules.append("Recovery time is elevated. Reduce the next hard session and prioritize easy aerobic work.")
    if fatigue.get("reasons"):
        rules.extend(fatigue["reasons"])
    if recovery.get("sleep_score", 100) < settings.low_sleep_score_threshold:
        rules.append("Sleep quality is low. Shift focus to sleep duration, hydration, and an easier next day.")
    if intensity.get("high_ratio", 0) > settings.high_intensity_ratio_threshold:
        rules.append("High-intensity distribution is above target. Add more Z2 volume and avoid stacking hard sessions.")
    if long_runs.get("latest_long_run_km", 0) < 18:
        rules.append("Recent long runs are short for stronger endurance development. Build a more consistent weekly long run.")
    if not rules:
        rules.append("Training load and recovery are reasonably balanced. Maintain current progression with small weekly increases.")
    return rules


def _daily_guidance(snapshot: dict[str, Any]) -> tuple[str, str]:
    recovery = snapshot.get("recovery", {})
    fatigue = snapshot.get("fatigue", {})
    readiness = snapshot.get("readiness", {})
    intensity = snapshot.get("intensity", {})
    settings = get_settings()

    if (
        fatigue.get("level") == "high"
        or recovery.get("recovery_time", 0) > settings.recovery_threshold_hours
        or recovery.get("sleep_score", 100) < settings.low_sleep_score_threshold
    ):
        return (
            "Keep today's session easy or take extra recovery if the legs still feel flat.",
            "Recovery markers are under pressure, so absorbing prior training is more useful than forcing intensity today.",
        )

    if readiness.get("score", 0) >= 75 and intensity.get("high_ratio", 0) <= settings.high_intensity_ratio_threshold:
        return (
            "You can keep the planned quality session, but stay disciplined with warm-up, pacing, and cooldown.",
            "Readiness is strong and fatigue is controlled, so a well-executed quality session should deliver adaptation without unnecessary risk.",
        )

    return (
        "Hold today's session in an aerobic range unless you feel clearly fresher than normal.",
        "An aerobic day keeps volume moving without adding fatigue when readiness is still building rather than peaking.",
    )


def _weekly_guidance(snapshot: dict[str, Any]) -> tuple[str, str]:
    weekly = snapshot.get("weekly_mileage", {})
    fatigue = snapshot.get("fatigue", {})
    intensity = snapshot.get("intensity", {})
    long_runs = snapshot.get("long_runs", {})
    current_7d = float(weekly.get("7d", 0))

    if fatigue.get("level") == "high":
        return (
            f"Keep next week near {max(current_7d - 4, 0):.0f}-{current_7d:.0f} km, reduce hard running, and protect recovery.",
            "Holding or slightly reducing load is better than pushing mileage when fatigue is already high, because adaptation happens after recovery.",
        )

    if intensity.get("high_ratio", 0) > get_settings().high_intensity_ratio_threshold:
        return (
            f"Target about {current_7d:.0f}-{current_7d + 4:.0f} km next week with one hard workout, one long run, and the rest clearly easy.",
            "Your current intensity balance is too aggressive, so shifting more time into easy running should improve durability and running-specific aerobic gains.",
        )

    if long_runs.get("latest_long_run_km", 0) < 18:
        return (
            f"Target {current_7d + 4:.0f}-{current_7d + 8:.0f} km next week and include one long run that extends running-specific endurance.",
            "A longer weekly long run is one of the clearest missing pieces for running readiness, so building it is more valuable than adding extra hard sessions.",
        )

    return (
        f"Target {current_7d + 4:.0f}-{current_7d + 8:.0f} km next week with one long run, one quality session, and the rest in Z2.",
        "A small progression in volume is effective when recovery is stable because it builds aerobic capacity without creating a large fatigue spike.",
    )


def _training_effectiveness(snapshot: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    positives: list[str] = []
    limiters: list[str] = []

    consistency = snapshot.get("consistency", {})
    if consistency.get("score", 0) >= 70:
        positives.append(f"Consistency is solid with {consistency.get('active_days', 0)} active days in the last 28 days.")
    else:
        limiters.append("Training consistency is not strong enough yet to fully support running progress.")

    long_runs = snapshot.get("long_runs", {})
    if long_runs.get("latest_long_run_km", 0) >= 18:
        positives.append(f"The latest long run reached {long_runs['latest_long_run_km']:.1f} km, which supports running endurance.")
    else:
        limiters.append("Long-run progression is still short for running-specific endurance demands.")

    vo2 = snapshot.get("vo2max", {})
    if vo2.get("trend") == "improving":
        positives.append(f"VO2max is trending up by {vo2.get('delta', 0):.2f}, showing aerobic development.")
    elif vo2.get("trend") == "declining":
        limiters.append("VO2max trend is slipping, which can signal reduced aerobic momentum or poor freshness.")

    efficiency = snapshot.get("efficiency", {})
    if efficiency.get("trend", 0) > 0.03:
        positives.append("Heart-rate-to-pace efficiency is improving, so you are getting more speed for the same effort.")
    elif efficiency.get("trend", 0) < -0.03:
        limiters.append("Heart-rate-to-pace efficiency has softened, so recent work may not be translating cleanly into better economy.")

    intensity = snapshot.get("intensity", {})
    if intensity.get("high_ratio", 0) <= settings.high_intensity_ratio_threshold:
        positives.append("The easy-to-hard balance is within range for sustainable running training.")
    else:
        limiters.append("Too much high-intensity volume is crowding out easy aerobic work and recovery.")

    fatigue = snapshot.get("fatigue", {})
    readiness = snapshot.get("readiness", {})
    if fatigue.get("level") == "high":
        limiters.append("Fatigue is high right now, which lowers the quality of adaptation from additional hard training.")
    elif readiness.get("score", 0) >= 70:
        positives.append("Readiness is supportive of training absorption rather than just surviving sessions.")

    prediction = snapshot.get("prediction", {})
    gap_minutes = float(prediction.get("gap_minutes", 0))
    if gap_minutes <= 0:
        positives.append("Current running prediction is on or ahead of goal pace.")
    elif gap_minutes >= 8:
        limiters.append(f"The current projection is still about {gap_minutes:.1f} minutes off goal pace.")

    if len(positives) >= 4 and len(limiters) <= 1:
        status = "effective"
        summary = "Your training is working overall because the main running signals are moving in the right direction."
    elif len(limiters) >= 3 or fatigue.get("level") == "high" or readiness.get("label") == "low":
        status = "not effective enough"
        summary = "Your training is producing some work, but the current mix is not effective enough for the goal until the main limiters improve."
    else:
        status = "mixed"
        summary = "Your training has productive elements, but a few weak points are limiting how efficiently it converts into running readiness."

    return {
        "status": status,
        "summary": summary,
        "working": positives,
        "limiters": limiters,
    }


def _fallback_response(snapshot: dict[str, Any], rules: list[str]) -> dict[str, Any]:
    prediction = snapshot["prediction"]
    readiness = snapshot["readiness"]
    fatigue = snapshot["fatigue"]
    daily_advice, daily_why = _daily_guidance(snapshot)
    weekly_advice, weekly_why = _weekly_guidance(snapshot)
    effectiveness = _training_effectiveness(snapshot)
    return {
        "daily_advice": daily_advice,
        "daily_why": daily_why,
        "weekly_advice": weekly_advice,
        "weekly_why": weekly_why,
        "fatigue_warning": fatigue["level"] == "high",
        "readiness_assessment": f"{readiness['label']} readiness with fatigue score {fatigue['score']}.",
        "confidence": prediction["confidence"],
        "training_effectiveness": effectiveness,
        "explanation": f"{effectiveness['summary']} Key checks: {' | '.join(rules[:3])}",
        "rule_recommendations": rules,
    }


def _normalize_llm_payload(llm_payload: dict[str, Any]) -> dict[str, Any]:
    normalized = {key: value for key, value in llm_payload.items() if value not in (None, "")}

    effect = normalized.get("training_effectiveness")
    if effect is not None and not isinstance(effect, dict):
        normalized.pop("training_effectiveness", None)
    elif isinstance(effect, dict):
        working = effect.get("working")
        limiters = effect.get("limiters")
        if isinstance(working, str):
            effect["working"] = [working]
        if isinstance(limiters, str):
            effect["limiters"] = [limiters]
        effect.setdefault("status", "mixed")
        effect.setdefault("summary", "")
        effect.setdefault("working", [])
        effect.setdefault("limiters", [])

    return normalized


class CoachingEngine:
    """Compatibility facade backed by the current guarded application workflow."""

    def __init__(self) -> None:
        from services.coaching_workflow import CoachingWorkflowService

        self.workflow = CoachingWorkflowService()

    def generate(self, session: Any, user: Any, athlete_note: str = "") -> dict[str, Any]:
        result = self.workflow.generate(session, user, athlete_note=athlete_note)
        return {**result, "daily_advice": result["summary"], "explanation": result["message_body"]}
