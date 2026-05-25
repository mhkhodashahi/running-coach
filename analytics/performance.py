"""Training, recovery, and running readiness analytics."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from config import get_settings

RUN_KEYWORDS = ("run", "running", "trail", "treadmill")
GOAL_RACE_DISTANCES = {
    "5k_pb": 5.0,
    "10k_pb": 10.0,
    "half_pb": 21.0975,
    "running_pb": 42.195,
}


def _safe_dataframe(df: pd.DataFrame, date_column: str = "date") -> pd.DataFrame:
    if df.empty:
        return df.copy()
    copy = df.copy()
    copy[date_column] = pd.to_datetime(copy[date_column])
    copy = copy.sort_values(date_column)
    return copy


def goal_distance_km(goal_type: str | None, target_distance_km: float | None = None) -> float:
    if target_distance_km and target_distance_km > 0:
        return float(target_distance_km)
    return GOAL_RACE_DISTANCES.get((goal_type or "").strip().lower(), 42.195)


def _running_activities(activities_df: pd.DataFrame) -> pd.DataFrame:
    if activities_df.empty:
        return activities_df.copy()
    return activities_df[
        activities_df["type"].fillna("").str.contains("|".join(RUN_KEYWORDS), case=False, na=False)
    ].copy()


def _reference_day(activities_df: pd.DataFrame, health_df: pd.DataFrame) -> pd.Timestamp:
    candidates: list[pd.Timestamp] = []
    if not activities_df.empty:
        candidates.append(pd.to_datetime(activities_df["date"]).max())
    if not health_df.empty:
        candidates.append(pd.to_datetime(health_df["date"]).max())
    return max(candidates) if candidates else pd.Timestamp.today().normalize()


def _window(df: pd.DataFrame, days: int, ref_day: pd.Timestamp, date_column: str = "date") -> pd.DataFrame:
    if df.empty:
        return df.copy()
    cutoff = ref_day - pd.Timedelta(days=days - 1)
    return df[df[date_column] >= cutoff].copy()


def weekly_mileage(activities_df: pd.DataFrame) -> dict[str, Any]:
    runs = _running_activities(_safe_dataframe(activities_df))
    ref_day = _reference_day(runs, pd.DataFrame())
    last_7 = _window(runs, 7, ref_day)["distance"].sum() if not runs.empty else 0.0
    last_28 = _window(runs, 28, ref_day)["distance"].sum() if not runs.empty else 0.0

    weekly_series = pd.DataFrame(columns=["week", "distance"])
    if not runs.empty:
        weekly_series = (
            runs.set_index("date")["distance"]
            .resample("W-MON")
            .sum()
            .reset_index()
            .rename(columns={"date": "week"})
        )
    return {
        "7d": round(float(last_7), 1),
        "28d": round(float(last_28), 1),
        "weekly_series": weekly_series,
    }


def vo2max_trend(health_df: pd.DataFrame) -> dict[str, Any]:
    health = _safe_dataframe(health_df)
    vo2 = health.dropna(subset=["vo2max"]).copy()
    if vo2.empty:
        return {"latest": None, "delta": 0.0, "slope": 0.0, "trend": "stable"}

    recent = vo2.tail(min(len(vo2), 8))
    values = recent["vo2max"].astype(float).to_numpy()
    slope = float(np.polyfit(np.arange(len(values)), values, 1)[0]) if len(values) > 1 else 0.0
    delta = float(values[-1] - values[0]) if len(values) > 1 else 0.0
    if slope > 0.08:
        trend = "improving"
    elif slope < -0.08:
        trend = "declining"
    else:
        trend = "stable"
    return {
        "latest": round(float(values[-1]), 1),
        "delta": round(delta, 2),
        "slope": round(slope, 3),
        "trend": trend,
        "series": vo2[["date", "vo2max"]],
    }


def hr_vs_pace_efficiency(activities_df: pd.DataFrame) -> dict[str, Any]:
    runs = _running_activities(_safe_dataframe(activities_df))
    runs = runs.dropna(subset=["pace", "avg_hr"])
    if runs.empty:
        return {"score": 0.0, "trend": 0.0, "series": runs}

    runs["speed_kmh"] = 60 / runs["pace"]
    runs["efficiency"] = runs["speed_kmh"] / runs["avg_hr"] * 100
    recent = runs.tail(4)["efficiency"].mean()
    previous = runs.iloc[:-4]["efficiency"].tail(4).mean() if len(runs) > 4 else recent
    trend = recent - previous
    return {
        "score": round(float(runs["efficiency"].tail(5).mean()), 2),
        "trend": round(float(trend), 2),
        "series": runs[["date", "pace", "avg_hr", "efficiency", "distance", "type"]],
    }


def intensity_distribution(activities_df: pd.DataFrame, user_max_hr: int | None) -> dict[str, Any]:
    runs = _running_activities(_safe_dataframe(activities_df))
    runs = runs.dropna(subset=["avg_hr"])
    if runs.empty or not user_max_hr:
        return {"distribution": {"Z2 / easy": 0.0, "Z3 / steady": 0.0, "Z4+ / hard": 0.0}, "high_ratio": 0.0}

    hr_ratio = runs["avg_hr"] / user_max_hr
    runs["zone"] = np.select(
        [hr_ratio < 0.78, hr_ratio < 0.88],
        ["Z2 / easy", "Z3 / steady"],
        default="Z4+ / hard",
    )
    grouped = runs.groupby("zone")["duration"].sum()
    total = float(grouped.sum()) or 1.0
    distribution = {zone: round(float(duration), 1) for zone, duration in grouped.items()}
    for zone in ("Z2 / easy", "Z3 / steady", "Z4+ / hard"):
        distribution.setdefault(zone, 0.0)
    return {
        "distribution": distribution,
        "high_ratio": round(distribution["Z4+ / hard"] / total, 3),
        "series": runs[["date", "type", "duration", "avg_hr", "zone"]],
    }


def long_run_progression(activities_df: pd.DataFrame) -> dict[str, Any]:
    runs = _running_activities(_safe_dataframe(activities_df))
    if runs.empty:
        return {"latest_long_run_km": 0.0, "progression": pd.DataFrame(columns=["week", "distance"])}

    long_runs = runs[runs["distance"] >= 16].copy()
    latest_long_run = float(long_runs["distance"].iloc[-1]) if not long_runs.empty else 0.0
    if long_runs.empty:
        return {
            "latest_long_run_km": round(latest_long_run, 1),
            "progression": pd.DataFrame(columns=["week", "distance"]),
        }

    progression = (
        long_runs.set_index("date")["distance"]
        .resample("W-MON")
        .max()
        .dropna()
        .reset_index()
        .rename(columns={"date": "week"})
    )
    return {
        "latest_long_run_km": round(latest_long_run, 1),
        "progression": progression,
    }


def consistency_score(activities_df: pd.DataFrame) -> dict[str, Any]:
    runs = _running_activities(_safe_dataframe(activities_df))
    ref_day = _reference_day(runs, pd.DataFrame())
    recent = _window(runs, 28, ref_day)
    if recent.empty:
        return {"score": 0.0, "active_days": 0}

    active_days = recent["date"].dt.normalize().nunique()
    weekly = (
        recent.set_index("date")["distance"]
        .resample("W-MON")
        .sum()
        .replace(0, np.nan)
        .dropna()
    )
    stability = 1.0
    if len(weekly) > 1:
        stability = max(0.0, 1 - float(weekly.std() / (weekly.mean() + 1e-6)))
    score = min(100.0, active_days / 20 * 60 + stability * 40)
    return {"score": round(score, 1), "active_days": int(active_days)}


def fatigue_score(
    activities_df: pd.DataFrame,
    health_df: pd.DataFrame,
    user_max_hr: int | None,
) -> dict[str, Any]:
    settings = get_settings()
    activities = _safe_dataframe(activities_df)
    health = _safe_dataframe(health_df)
    ref_day = _reference_day(activities, health)
    recent_health = _window(health, 7, ref_day)
    baseline_health = _window(health, 28, ref_day)
    recent_activities = _window(activities, 7, ref_day)
    mileage = weekly_mileage(activities)
    intensity = intensity_distribution(activities, user_max_hr)

    reasons: list[str] = []
    score = 0.0
    latest = recent_health.iloc[-1] if not recent_health.empty else None

    if latest is not None and not baseline_health.empty:
        baseline_rhr = float(baseline_health["resting_hr"].dropna().mean()) if baseline_health["resting_hr"].notna().any() else 0.0
        latest_rhr = float(latest.get("resting_hr") or 0.0)
        rhr_delta = latest_rhr - baseline_rhr
        if rhr_delta > 0:
            score += min(24.0, rhr_delta * 4)
            if rhr_delta >= settings.elevated_resting_hr_threshold:
                reasons.append(f"Resting HR is elevated by {rhr_delta:.1f} bpm versus 28-day baseline.")

        baseline_hrv = float(baseline_health["hrv"].dropna().mean()) if baseline_health["hrv"].notna().any() else 0.0
        latest_hrv = float(latest.get("hrv") or 0.0)
        hrv_drop = baseline_hrv - latest_hrv
        if hrv_drop > 0:
            score += min(18.0, hrv_drop * 0.8)
            if hrv_drop > 6:
                reasons.append(f"HRV is down by {hrv_drop:.1f} ms against baseline.")

        sleep_score = float(latest.get("sleep_score") or 0.0)
        sleep_duration = float(latest.get("sleep_duration") or 0.0)
        score += max(0.0, 78 - sleep_score) * 0.5
        score += max(0.0, 7.5 - sleep_duration) * 5
        if sleep_score and sleep_score < settings.low_sleep_score_threshold:
            reasons.append("Recent sleep quality is below target for a gaol build.")

        recovery_time = float(latest.get("recovery_time") or 0.0)
        score += min(20.0, recovery_time / settings.recovery_threshold_hours * 20)
        if recovery_time > settings.recovery_threshold_hours:
            reasons.append(f"Garmin recovery time is still high at {recovery_time:.0f} hours.")

    recent_load = float(recent_activities["duration"].sum())
    chronic_load = mileage["28d"] / 4 if mileage["28d"] else 0.0
    if recent_load and chronic_load:
        score += max(0.0, (mileage["7d"] - chronic_load * 1.15) * 1.6)

    if intensity["high_ratio"] > settings.high_intensity_ratio_threshold:
        score += (intensity["high_ratio"] - settings.high_intensity_ratio_threshold) * 100
        reasons.append("High-intensity volume is crowding out easy aerobic work.")

    score = float(np.clip(score, 0, 100))
    if score >= 70:
        level = "high"
    elif score >= 40:
        level = "moderate"
    else:
        level = "low"

    return {"score": round(score, 1), "level": level, "reasons": reasons}


def readiness_score(
    activities_df: pd.DataFrame,
    health_df: pd.DataFrame,
    user_max_hr: int | None,
) -> dict[str, Any]:
    fatigue = fatigue_score(activities_df, health_df, user_max_hr)
    health = _safe_dataframe(health_df)
    latest = health.iloc[-1] if not health.empty else None
    consistency = consistency_score(activities_df)["score"]
    body_battery = float(latest.get("body_battery") or 60.0) if latest is not None else 60.0
    sleep_score = float(latest.get("sleep_score") or 75.0) if latest is not None else 75.0
    readiness = (100 - fatigue["score"]) * 0.55 + body_battery * 0.25 + sleep_score * 0.10 + consistency * 0.10
    readiness = float(np.clip(readiness, 0, 100))
    if readiness >= 75:
        label = "high"
    elif readiness >= 55:
        label = "building"
    else:
        label = "low"
    return {"score": round(readiness, 1), "label": label}


def _weighted_average(values: list[tuple[float, float]]) -> float | None:
    if not values:
        return None
    weighted_sum = sum(value * weight for value, weight in values)
    total_weight = sum(weight for _, weight in values)
    return weighted_sum / total_weight if total_weight else None


def _race_equivalent_pace_candidates(
    runs: pd.DataFrame,
    ref_day: pd.Timestamp,
    user_max_hr: int | None,
    race_distance_km: float,
) -> list[tuple[float, float]]:
    eligible = _window(runs.dropna(subset=["distance", "duration", "pace"]), 70, ref_day)
    eligible = eligible[(eligible["distance"] >= 5) & (eligible["duration"] >= 20)].copy()
    if eligible.empty:
        return []

    candidates: list[tuple[float, float]] = []
    for row in eligible.itertuples():
        distance = float(row.distance)
        duration = float(row.duration)
        days_ago = max((ref_day.normalize() - pd.Timestamp(row.date).normalize()).days, 0)

        effort_adjustment = 1.0
        if user_max_hr and pd.notna(getattr(row, "avg_hr", None)):
            hr_ratio = float(row.avg_hr) / user_max_hr
            effort_adjustment -= min(0.05, max(0.0, 0.82 - hr_ratio) * 0.30)
            effort_adjustment += min(0.03, max(0.0, hr_ratio - 0.90) * 0.20)

        # Shorter runs extrapolate less reliably than long steady efforts.
        exponent = 1.045 + float(np.clip((12.0 - distance) / 220, -0.012, 0.028))
        projected_minutes = duration * effort_adjustment * (race_distance_km / distance) ** exponent
        projected_pace = projected_minutes / race_distance_km

        recency_weight = float(np.clip(1.0 - days_ago / 84, 0.35, 1.0))
        distance_weight = float(np.clip(distance / 21.1, 0.35, 1.15))
        hr_weight = 0.8
        if user_max_hr and pd.notna(getattr(row, "avg_hr", None)):
            hr_ratio = float(row.avg_hr) / user_max_hr
            hr_weight = float(np.clip((hr_ratio - 0.68) / 0.16, 0.45, 1.0))

        candidates.append((projected_pace, recency_weight * distance_weight * hr_weight))

    candidates.sort(key=lambda item: item[0])
    keep_count = max(3, min(len(candidates), (len(candidates) + 1) // 2 + 1))
    return candidates[:keep_count]


def _training_endurance_penalty(
    runs: pd.DataFrame,
    ref_day: pd.Timestamp,
    consistency: float,
) -> tuple[float, float, float]:
    recent = _window(runs, 42, ref_day)
    longest_recent = float(recent["distance"].max()) if not recent.empty else 0.0
    weekly_average = weekly_mileage(runs)["28d"] / 4 if not runs.empty else 0.0

    penalty = 1.0
    if weekly_average < 32:
        penalty += min(0.12, (32 - weekly_average) / 220)
    elif weekly_average > 55:
        penalty -= min(0.03, (weekly_average - 55) / 300)

    if longest_recent < 26:
        penalty += min(0.10, (26 - longest_recent) / 170)
    elif longest_recent > 30:
        penalty -= min(0.02, (longest_recent - 30) / 120)

    if consistency < 55:
        penalty += min(0.06, (55 - consistency) / 500)

    return float(np.clip(penalty, 0.9, 1.2)), weekly_average, longest_recent


def training_load_series(activities_df: pd.DataFrame) -> pd.DataFrame:
    activities = _safe_dataframe(activities_df)
    if activities.empty:
        return pd.DataFrame(columns=["date", "training_load"])
    activities["training_load"] = (
        activities["distance"].fillna(0) * 3
        + activities["duration"].fillna(0) * 0.3
        + activities["aerobic_effect"].fillna(0) * 12
        + activities["anaerobic_effect"].fillna(0) * 16
    )
    return activities[["date", "training_load"]]


def predict_finish_time_for_distance(
    user: Any,
    activities_df: pd.DataFrame,
    health_df: pd.DataFrame,
    race_distance_km: float,
    target_time_minutes: float | None = None,
) -> dict[str, Any]:
    runs = _running_activities(_safe_dataframe(activities_df)).dropna(subset=["distance", "duration", "pace"])
    health = _safe_dataframe(health_df)
    settings = get_settings()
    race_distance_km = max(float(race_distance_km), 1.0)
    goal_minutes = float(target_time_minutes or settings.sub_four_goal_minutes)
    goal_pace = goal_minutes / race_distance_km

    if runs.empty:
        predicted_pace = goal_pace * 1.08
        weekly_average = 0.0
        longest_recent = 0.0
        consistency = 0.0
        readiness = readiness_score(runs, health, getattr(user, "max_hr", None))["score"]
        fatigue = fatigue_score(runs, health, getattr(user, "max_hr", None))["score"]
        candidate_count = 0
    else:
        ref_day = _reference_day(runs, health)
        consistency = consistency_score(runs)["score"]
        readiness = readiness_score(runs, health, getattr(user, "max_hr", None))["score"]
        fatigue = fatigue_score(runs, health, getattr(user, "max_hr", None))["score"]
        candidate_paces = _race_equivalent_pace_candidates(
            runs,
            ref_day,
            getattr(user, "max_hr", None),
            race_distance_km,
        )
        candidate_count = len(candidate_paces)

        long_runs = _window(runs[runs["distance"] >= 18], 56, ref_day)
        steady_runs = _window(runs[(runs["distance"] >= 10) & (runs["distance"] <= 18)], 56, ref_day)
        latest_vo2 = vo2max_trend(health)["latest"]
        if not long_runs.empty:
            long_run_factor = 0.975 if race_distance_km >= 21 else 0.99
            candidate_paces.append((float(long_runs.tail(3)["pace"].median()) * long_run_factor, 0.28))
        if not steady_runs.empty:
            steady_factor = 0.99 if race_distance_km <= 10 else 1.01
            candidate_paces.append((float(steady_runs.nsmallest(4, "pace")["pace"].median()) * steady_factor, 0.24))
        if latest_vo2 is not None:
            vo2_factor = np.clip(42.195 / race_distance_km, 1.0, 2.0)
            candidate_paces.append((max(3.2, 7.00 - latest_vo2 * (0.028 * vo2_factor)), 0.18))
        candidate_paces.append((float(runs["pace"].median()) * 1.12, 0.08))

        predicted_pace = _weighted_average(candidate_paces) or goal_pace * 1.05
        endurance_penalty, weekly_average, longest_recent = _training_endurance_penalty(runs, ref_day, consistency)
        if race_distance_km >= 21:
            predicted_pace *= endurance_penalty
        elif race_distance_km <= 10:
            predicted_pace *= float(np.clip(endurance_penalty - 0.02, 0.9, 1.12))
        else:
            predicted_pace *= float(np.clip(endurance_penalty - 0.01, 0.9, 1.16))
        predicted_pace += max(0.0, fatigue - 45) / 170
        predicted_pace -= max(0.0, readiness - 70) / 260
        predicted_pace -= max(0.0, consistency - 65) / 900
        predicted_pace = float(np.clip(predicted_pace, 3.2, 8.5))

    predicted_minutes = predicted_pace * race_distance_km
    gap_minutes = predicted_minutes - goal_minutes
    confidence = float(
        np.clip(
            32
            + min(18.0, candidate_count * 1.8)
            + min(14.0, weekly_average / 3.5)
            + min(8.0, longest_recent / 4.0)
            + max(0.0, readiness - 55) * 0.35
            + max(0.0, consistency - 55) * 0.18
            - max(0.0, fatigue - 45) * 0.45
            - max(0.0, gap_minutes) * 3.5
            + max(0.0, -gap_minutes) * 1.2,
            5,
            95,
        )
    )
    return {
        "race_distance_km": round(race_distance_km, 3),
        "predicted_pace": round(predicted_pace, 2),
        "predicted_minutes": round(predicted_minutes, 1),
        "gap_minutes": round(gap_minutes, 1),
        "confidence": round(confidence, 1),
    }


def estimated_running_finish_time(
    user: Any,
    activities_df: pd.DataFrame,
    health_df: pd.DataFrame,
) -> dict[str, Any]:
    return predict_finish_time_for_distance(user, activities_df, health_df, 42.195)


def build_goal_projection(
    user: Any,
    activities_df: pd.DataFrame,
    health_df: pd.DataFrame,
    goal_type: str,
    target_time_minutes: float,
    target_distance_km: float | None = None,
) -> dict[str, Any]:
    race_distance_km = goal_distance_km(goal_type, target_distance_km)
    prediction = predict_finish_time_for_distance(
        user,
        activities_df,
        health_df,
        race_distance_km,
        target_time_minutes=target_time_minutes,
    )
    target_time_minutes = float(target_time_minutes)
    target_pace = target_time_minutes / race_distance_km
    predicted_minutes = float(prediction["predicted_minutes"])
    gap_minutes = predicted_minutes - target_time_minutes
    return {
        "goal_type": goal_type,
        "race_distance_km": round(race_distance_km, 3),
        "target_time_minutes": round(target_time_minutes, 1),
        "target_pace": round(target_pace, 2),
        "predicted_time_minutes": round(predicted_minutes, 1),
        "predicted_pace": round(float(prediction["predicted_pace"]), 2),
        "gap_minutes": round(gap_minutes, 1),
        "confidence": float(prediction["confidence"]),
        "status": "on_track" if gap_minutes <= 0 else "behind",
    }


def goal_time_minutes(goal_time: str | float | int | None) -> float:
    if goal_time is None:
        return 240.0
    if isinstance(goal_time, (float, int)):
        return float(goal_time)
    hours, minutes, seconds = [int(part) for part in str(goal_time).split(":")]
    return hours * 60 + minutes + seconds / 60


def latest_recovery_snapshot(health_df: pd.DataFrame) -> dict[str, Any]:
    health = _safe_dataframe(health_df)
    if health.empty:
        return {}
    latest = health.iloc[-1]
    return {
        "sleep_duration": float(latest.get("sleep_duration") or 0.0),
        "sleep_score": float(latest.get("sleep_score") or 0.0),
        "resting_hr": float(latest.get("resting_hr") or 0.0),
        "hrv": float(latest.get("hrv") or 0.0),
        "stress": float(latest.get("stress") or 0.0),
        "body_battery": float(latest.get("body_battery") or 0.0),
        "recovery_time": float(latest.get("recovery_time") or 0.0),
        "vo2max": float(latest.get("vo2max") or 0.0),
    }


def sleep_performance_correlation(activities_df: pd.DataFrame, health_df: pd.DataFrame) -> dict[str, Any]:
    runs = _running_activities(_safe_dataframe(activities_df))
    health = _safe_dataframe(health_df)
    if runs.empty or health.empty:
        return {"correlation": 0.0, "series": pd.DataFrame(columns=["date", "sleep_score", "pace", "avg_hr"])}

    merged = runs.merge(health[["date", "sleep_score", "sleep_duration"]], on="date", how="inner")
    if merged.empty:
        return {"correlation": 0.0, "series": merged}
    correlation = float(merged["sleep_score"].corr(merged["pace"])) if len(merged) > 1 else 0.0
    return {"correlation": round(correlation, 3), "series": merged}


def build_training_snapshot(
    user: Any,
    activities_df: pd.DataFrame,
    health_df: pd.DataFrame,
    goal: Any | None = None,
) -> dict[str, Any]:
    """Build a single analytics snapshot used by the UI and coaching engine."""

    weekly = weekly_mileage(activities_df)
    vo2 = vo2max_trend(health_df)
    efficiency = hr_vs_pace_efficiency(activities_df)
    fatigue = fatigue_score(activities_df, health_df, getattr(user, "max_hr", None))
    readiness = readiness_score(activities_df, health_df, getattr(user, "max_hr", None))
    consistency = consistency_score(activities_df)
    long_runs = long_run_progression(activities_df)
    intensity = intensity_distribution(activities_df, getattr(user, "max_hr", None))
    prediction = estimated_running_finish_time(user, activities_df, health_df)
    recovery = latest_recovery_snapshot(health_df)
    load = training_load_series(activities_df)
    correlations = sleep_performance_correlation(activities_df, health_df)
    active_goal_projection = None
    goal_pace = round(get_settings().goal_pace_min_per_km, 2)
    if goal is not None:
        active_goal_projection = build_goal_projection(
            user,
            activities_df,
            health_df,
            getattr(goal, "goal_type", "running_pb"),
            float(getattr(goal, "target_time_minutes", 240.0)),
            float(getattr(goal, "target_distance_km", 42.195)),
        )
        goal_pace = active_goal_projection["target_pace"]

    return {
        "weekly_mileage": weekly,
        "vo2max": vo2,
        "efficiency": efficiency,
        "fatigue": fatigue,
        "readiness": readiness,
        "consistency": consistency,
        "long_runs": long_runs,
        "intensity": intensity,
        "prediction": prediction,
        "active_goal_projection": active_goal_projection,
        "recovery": recovery,
        "training_load": load,
        "correlations": correlations,
        "goal_pace": goal_pace,
    }
