"""Repository helpers for database access."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

import pandas as pd
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from body_progress.domain import BodyScanCreate, BodyScanProcessingResult, BodyScanSummary
from config import get_settings
from db.models import (
    Activity,
    ActivityCoachingInsight,
    ActivityLap,
    ActivityTrackPoint,
    BodyScan,
    BodyScanInsight,
    CoachingDecision,
    EmailDelivery,
    Goal,
    HealthMetric,
    LLMMemory,
    NutritionEntry,
    PredictionSnapshot,
    User,
)


def get_or_create_default_user(session: Session, default_user_id: int) -> User:
    """Return the default user profile, creating a demo profile when missing."""

    user = session.get(User, default_user_id)
    if user:
        _backfill_legacy_default_profile(user)
        session.flush()
        return user

    user = User(
        id=default_user_id,
        name="Mohammad",
        age=39,
        gender="male",
        weight=89.0,
        height=178.0,
        max_hr=184,
        training_days_per_week=5,
        injury_notes=None,
        running_date=date(2026, 9, 27),
    )
    session.add(user)
    session.flush()
    return user


def _backfill_legacy_default_profile(user: User) -> None:
    """Update old demo defaults without overwriting user-edited profiles."""

    if user.name == "Mohammad" and user.age == 34:
        user.age = 39
    if user.name == "Mohammad" and user.weight == 73.0:
        user.weight = 89.0
    if user.name == "Mohammad" and user.max_hr == 188:
        user.max_hr = 184


def get_or_create_default_goal(session: Session, user: User) -> Goal:
    """Create a default running goal when the athlete has not configured one yet."""

    goal = session.scalars(
        select(Goal)
        .where(Goal.user_id == user.id)
        .order_by(Goal.is_active.desc(), Goal.created_at.asc())
    ).first()
    if goal is not None:
        return goal

    goal = Goal(
        user_id=user.id,
        name="Primary Running Goal",
        goal_type="running_pb",
        target_distance_km=42.195,
        target_time_minutes=get_settings().sub_four_goal_minutes,
        target_date=user.running_date,
        priority="A",
        status="active",
        is_active=True,
        notes="Default active goal created from app settings.",
    )
    session.add(goal)
    session.flush()
    return goal


def update_user_profile(session: Session, user_id: int, payload: dict[str, Any]) -> User:
    """Update the user profile."""

    user = session.get(User, user_id)
    if user is None:
        raise ValueError(f"Unknown user id: {user_id}")

    for field, value in payload.items():
        setattr(user, field, value)
    session.flush()
    return user


def list_goals(session: Session, user_id: int) -> list[Goal]:
    """Return configured goals for a user."""

    return list(
        session.scalars(
            select(Goal)
            .where(Goal.user_id == user_id)
            .order_by(Goal.is_active.desc(), Goal.target_date.asc(), Goal.created_at.desc())
        ).all()
    )


def get_goal(session: Session, goal_id: int) -> Goal | None:
    """Return one goal by id."""

    return session.get(Goal, goal_id)


def get_active_goal(session: Session, user_id: int) -> Goal | None:
    """Return the active goal for a user."""

    return session.scalars(
        select(Goal)
        .where(Goal.user_id == user_id, Goal.is_active.is_(True))
        .order_by(Goal.created_at.desc())
    ).first()


def create_goal(session: Session, user_id: int, payload: dict[str, Any]) -> Goal:
    """Create a new user goal."""

    goal = Goal(user_id=user_id, **payload)
    session.add(goal)
    session.flush()
    if goal.is_active:
        set_active_goal(session, user_id, goal.id)
    return goal


def update_goal(session: Session, goal_id: int, payload: dict[str, Any]) -> Goal:
    """Update a goal."""

    goal = session.get(Goal, goal_id)
    if goal is None:
        raise ValueError(f"Unknown goal id: {goal_id}")

    for field, value in payload.items():
        setattr(goal, field, value)
    session.flush()
    if goal.is_active:
        set_active_goal(session, goal.user_id, goal.id)
    return goal


def set_active_goal(session: Session, user_id: int, goal_id: int) -> Goal:
    """Mark one goal as active and clear the rest."""

    goals = list(
        session.scalars(select(Goal).where(Goal.user_id == user_id)).all()
    )
    selected: Goal | None = None
    for goal in goals:
        goal.is_active = goal.id == goal_id
        if goal.id == goal_id:
            goal.status = "active"
            selected = goal
    if selected is None:
        raise ValueError(f"Unknown goal id: {goal_id}")
    session.flush()
    return selected


def activities_count(session: Session, user_id: int) -> int:
    """Return the number of stored activities."""

    return len(session.scalars(select(Activity.id).where(Activity.user_id == user_id)).all())


def health_metrics_count(session: Session, user_id: int) -> int:
    """Return the number of stored health rows."""

    return len(session.scalars(select(HealthMetric.id).where(HealthMetric.user_id == user_id)).all())


def bulk_upsert_activities(session: Session, rows: list[dict[str, Any]]) -> int:
    """Insert or update activity rows."""

    inserted = 0
    for row in rows:
        external_id = row.get("external_id")
        query = select(Activity).where(Activity.user_id == row["user_id"])
        if external_id:
            query = query.where(Activity.external_id == external_id)
        else:
            query = query.where(
                Activity.date == row["date"],
                Activity.type == row["type"],
                Activity.distance == row["distance"],
            )
        activity = session.scalars(query).first()
        if activity is None:
            activity = Activity(**row)
            session.add(activity)
            inserted += 1
            continue

        for field, value in row.items():
            setattr(activity, field, value)
    session.flush()
    return inserted


def activity_ids_by_external_id(session: Session, user_id: int, external_ids: list[str]) -> dict[str, int]:
    """Return local activity ids keyed by Garmin/external id."""

    if not external_ids:
        return {}
    rows = session.execute(
        select(Activity.external_id, Activity.id).where(
            Activity.user_id == user_id,
            Activity.external_id.in_([str(external_id) for external_id in external_ids]),
        )
    ).all()
    return {str(external_id): int(activity_id) for external_id, activity_id in rows if external_id}


def replace_activity_track_points(session: Session, activity_id: int, rows: list[dict[str, Any]]) -> int:
    """Replace stored GPS/metric stream points for one activity."""

    session.execute(delete(ActivityTrackPoint).where(ActivityTrackPoint.activity_id == activity_id))
    if not rows:
        session.flush()
        return 0

    for row in rows:
        session.add(ActivityTrackPoint(activity_id=activity_id, **row))
    session.flush()
    return len(rows)


def replace_activity_laps(session: Session, activity_id: int, rows: list[dict[str, Any]]) -> int:
    """Replace stored laps/splits for one activity."""

    session.execute(delete(ActivityLap).where(ActivityLap.activity_id == activity_id))
    if not rows:
        session.flush()
        return 0

    for row in rows:
        session.add(ActivityLap(activity_id=activity_id, **row))
    session.flush()
    return len(rows)


def track_points_dataframe(session: Session, activity_id: int) -> pd.DataFrame:
    """Return GPS/metric stream points for an activity."""

    query = text(
        """
        SELECT id, activity_id, point_index, timestamp, elapsed_seconds, distance_km,
               latitude, longitude, elevation, pace, speed, heart_rate, cadence
        FROM activity_track_points
        WHERE activity_id = :activity_id
        ORDER BY point_index ASC
        """
    )
    df = pd.read_sql_query(query, session.bind, params={"activity_id": activity_id})
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def activity_laps_dataframe(session: Session, activity_id: int) -> pd.DataFrame:
    """Return laps/splits for an activity."""

    query = text(
        """
        SELECT id, activity_id, lap_index, lap_type, start_time, duration, distance,
               pace, avg_hr, max_hr, elevation_gain, avg_cadence
        FROM activity_laps
        WHERE activity_id = :activity_id
        ORDER BY lap_index ASC
        """
    )
    df = pd.read_sql_query(query, session.bind, params={"activity_id": activity_id})
    if not df.empty:
        df["start_time"] = pd.to_datetime(df["start_time"])
    return df


def get_activity(session: Session, activity_id: int, user_id: int | None = None) -> Activity | None:
    """Return one activity, optionally scoped to a user."""

    query = select(Activity).where(Activity.id == activity_id)
    if user_id is not None:
        query = query.where(Activity.user_id == user_id)
    return session.scalars(query).first()


def get_activity_coaching_insight(session: Session, activity_id: int, user_id: int) -> ActivityCoachingInsight | None:
    """Return the stored coach opinion for one activity."""

    return session.scalars(
        select(ActivityCoachingInsight).where(
            ActivityCoachingInsight.activity_id == activity_id,
            ActivityCoachingInsight.user_id == user_id,
        )
    ).first()


def upsert_activity_coaching_insight(
    session: Session,
    *,
    user_id: int,
    activity_id: int,
    summary: str,
    payload_json: str,
    prompt_context_json: str,
    model_provider: str | None,
    model_name: str | None,
) -> ActivityCoachingInsight:
    """Create or replace the stored coach opinion for one activity."""

    insight = get_activity_coaching_insight(session, activity_id=activity_id, user_id=user_id)
    if insight is None:
        insight = ActivityCoachingInsight(
            user_id=user_id,
            activity_id=activity_id,
            summary=summary,
            payload_json=payload_json,
            prompt_context_json=prompt_context_json,
            model_provider=model_provider,
            model_name=model_name,
        )
        session.add(insight)
    else:
        insight.summary = summary
        insight.payload_json = payload_json
        insight.prompt_context_json = prompt_context_json
        insight.model_provider = model_provider
        insight.model_name = model_name
        insight.updated_at = datetime.utcnow()
    session.flush()
    return insight


def upsert_prediction_snapshot(
    session: Session,
    *,
    user_id: int,
    activity_id: int | None,
    goal_id: int | None,
    prediction_date: date,
    race_distance_km: float,
    predicted_time_minutes: float,
    predicted_pace: float,
    gap_minutes: float,
    confidence: float,
    payload_json: str,
) -> PredictionSnapshot:
    """Create or update one prediction snapshot for an activity/goal pair."""

    query = select(PredictionSnapshot).where(
        PredictionSnapshot.user_id == user_id,
        PredictionSnapshot.goal_id == goal_id,
    )
    if activity_id is None:
        query = query.where(PredictionSnapshot.activity_id.is_(None), PredictionSnapshot.prediction_date == prediction_date)
    else:
        query = query.where(PredictionSnapshot.activity_id == activity_id)
    snapshot = session.scalars(query).first()
    if snapshot is None:
        snapshot = PredictionSnapshot(
            user_id=user_id,
            activity_id=activity_id,
            goal_id=goal_id,
            prediction_date=prediction_date,
            race_distance_km=race_distance_km,
            predicted_time_minutes=predicted_time_minutes,
            predicted_pace=predicted_pace,
            gap_minutes=gap_minutes,
            confidence=confidence,
            payload_json=payload_json,
        )
        session.add(snapshot)
    else:
        snapshot.prediction_date = prediction_date
        snapshot.race_distance_km = race_distance_km
        snapshot.predicted_time_minutes = predicted_time_minutes
        snapshot.predicted_pace = predicted_pace
        snapshot.gap_minutes = gap_minutes
        snapshot.confidence = confidence
        snapshot.payload_json = payload_json
    session.flush()
    return snapshot


def prediction_snapshots_dataframe(session: Session, user_id: int) -> pd.DataFrame:
    """Return stored prediction snapshots."""

    query = text(
        """
        SELECT ps.id, ps.user_id, ps.activity_id, ps.goal_id, ps.prediction_date,
               ps.race_distance_km, ps.predicted_time_minutes, ps.predicted_pace,
               ps.gap_minutes, ps.confidence, ps.payload_json, ps.created_at,
               a.activity_name, a.type AS activity_type, a.distance AS activity_distance
        FROM prediction_snapshots ps
        LEFT JOIN activities a ON a.id = ps.activity_id
        WHERE ps.user_id = :user_id
        ORDER BY ps.prediction_date ASC, ps.created_at ASC
        """
    )
    df = pd.read_sql_query(query, session.bind, params={"user_id": user_id})
    if not df.empty:
        for column in ("prediction_date", "created_at"):
            df[column] = pd.to_datetime(df[column])
    return df


def bulk_upsert_health_metrics(session: Session, rows: list[dict[str, Any]]) -> int:
    """Insert or update health metric rows."""

    inserted = 0
    for row in rows:
        metric = session.scalars(
            select(HealthMetric).where(
                HealthMetric.user_id == row["user_id"],
                HealthMetric.date == row["date"],
            )
        ).first()
        if metric is None:
            metric = HealthMetric(**row)
            session.add(metric)
            inserted += 1
            continue

        for field, value in row.items():
            setattr(metric, field, value)
    session.flush()
    return inserted


def activities_dataframe(session: Session, user_id: int) -> pd.DataFrame:
    """Return activities as a pandas DataFrame."""

    query = text(
        """
        SELECT id, user_id, external_id, activity_name, date, type, distance, duration, pace,
               avg_hr, max_hr, cadence, elevation, training_effect,
               aerobic_effect, anaerobic_effect, notes
        FROM activities
        WHERE user_id = :user_id
        ORDER BY date ASC
        """
    )
    df = pd.read_sql_query(query, session.bind, params={"user_id": user_id})
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def health_metrics_dataframe(session: Session, user_id: int) -> pd.DataFrame:
    """Return health metrics as a pandas DataFrame."""

    query = text(
        """
        SELECT id, user_id, date, sleep_duration, sleep_score, resting_hr, hrv,
               stress, body_battery, recovery_time, vo2max
        FROM health_metrics
        WHERE user_id = :user_id
        ORDER BY date ASC
        """
    )
    df = pd.read_sql_query(query, session.bind, params={"user_id": user_id})
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def nutrition_entries_dataframe(session: Session, user_id: int) -> pd.DataFrame:
    """Return nutrition log rows as a dataframe."""

    query = text(
        """
        SELECT id, user_id, entry_date, meal_type, food_name, calories,
               protein_g, carbs_g, fat_g, notes, created_at
        FROM nutrition_entries
        WHERE user_id = :user_id
        ORDER BY entry_date ASC, created_at ASC
        """
    )
    df = pd.read_sql_query(query, session.bind, params={"user_id": user_id})
    if not df.empty:
        for column in ("entry_date", "created_at"):
            df[column] = pd.to_datetime(df[column])
    return df


def create_nutrition_entry(session: Session, user_id: int, payload: dict[str, Any]) -> NutritionEntry:
    """Create one nutrition log entry."""

    entry = NutritionEntry(
        user_id=user_id,
        entry_date=payload["entry_date"],
        meal_type=payload.get("meal_type") or "meal",
        food_name=payload["food_name"],
        calories=float(payload.get("calories") or 0.0),
        protein_g=float(payload.get("protein_g") or 0.0),
        carbs_g=float(payload.get("carbs_g") or 0.0),
        fat_g=float(payload.get("fat_g") or 0.0),
        notes=(payload.get("notes") or "").strip() or None,
    )
    session.add(entry)
    session.flush()
    return entry


def delete_nutrition_entry(session: Session, entry_id: int, user_id: int) -> None:
    """Delete one nutrition entry owned by a user."""

    entry = session.get(NutritionEntry, entry_id)
    if entry is None or entry.user_id != user_id:
        raise ValueError(f"Unknown nutrition entry id: {entry_id}")
    session.delete(entry)
    session.flush()


def create_body_scan(session: Session, payload: BodyScanCreate) -> BodyScan:
    """Register a body progress scan."""

    scan = BodyScan(
        user_id=payload.user_id,
        scan_date=payload.scan_date,
        view=payload.view,
        source_image_path=str(payload.source_image_path) if payload.consent_to_store_image else None,
        consent_to_store_image=payload.consent_to_store_image,
        notes=payload.notes.strip() or None,
    )
    session.add(scan)
    session.flush()
    return scan


def update_body_scan_result(session: Session, scan_id: int, result: BodyScanProcessingResult) -> BodyScan:
    """Persist processor outputs for one body scan."""

    scan = session.get(BodyScan, scan_id)
    if scan is None:
        raise ValueError(f"Unknown body scan id: {scan_id}")

    scan.status = result.status
    scan.preview_image_path = result.preview_image_path
    scan.mesh_path = result.mesh_path
    scan.keypoints_json = json.dumps(result.keypoints_json) if result.keypoints_json is not None else None
    scan.measurements_json = json.dumps(result.measurements_json) if result.measurements_json is not None else None
    scan.pose_quality = result.pose_quality
    scan.processor_name = result.processor_name
    scan.error_message = result.error_message
    session.flush()
    return scan


def list_body_scans(session: Session, user_id: int) -> list[BodyScanSummary]:
    """Return body scans as portable summaries."""

    rows = session.scalars(
        select(BodyScan).where(BodyScan.user_id == user_id).order_by(BodyScan.scan_date.desc(), BodyScan.created_at.desc())
    ).all()
    return [
        BodyScanSummary(
            id=row.id,
            user_id=row.user_id,
            scan_date=row.scan_date,
            view=row.view,  # type: ignore[arg-type]
            status=row.status,  # type: ignore[arg-type]
            source_image_path=row.source_image_path,
            preview_image_path=row.preview_image_path,
            mesh_path=row.mesh_path,
            pose_quality=row.pose_quality,
            notes=row.notes,
            created_at=row.created_at,
        )
        for row in rows
    ]


def body_scans_dataframe(session: Session, user_id: int) -> pd.DataFrame:
    """Return body scan timeline rows as a dataframe."""

    query = text(
        """
        SELECT id, user_id, scan_date, view, status, source_image_path,
               preview_image_path, mesh_path, keypoints_json, measurements_json,
               pose_quality, processor_name,
               error_message, consent_to_store_image, notes, created_at, updated_at
        FROM body_scans
        WHERE user_id = :user_id
        ORDER BY scan_date ASC, created_at ASC
        """
    )
    df = pd.read_sql_query(query, session.bind, params={"user_id": user_id})
    if not df.empty:
        for column in ("scan_date", "created_at", "updated_at"):
            df[column] = pd.to_datetime(df[column])
    return df


def body_scan_insights_dataframe(session: Session, user_id: int) -> pd.DataFrame:
    """Return stored body scan LLM insights as a dataframe."""

    query = text(
        """
        SELECT id, user_id, insight_date, scan_ids_json, summary, payload_json,
               prompt_context_json, model_provider, model_name, created_at
        FROM body_scan_insights
        WHERE user_id = :user_id
        ORDER BY insight_date DESC, created_at DESC
        """
    )
    df = pd.read_sql_query(query, session.bind, params={"user_id": user_id})
    if not df.empty:
        for column in ("insight_date", "created_at"):
            df[column] = pd.to_datetime(df[column])
    return df


def store_body_scan_insight(
    session: Session,
    user_id: int,
    insight_date: date,
    scan_ids: list[int],
    summary: str,
    payload_json: str,
    prompt_context_json: str,
    model_provider: str | None,
    model_name: str | None,
) -> BodyScanInsight:
    """Persist one LLM interpretation of body scan history."""

    insight = BodyScanInsight(
        user_id=user_id,
        insight_date=insight_date,
        scan_ids_json=json.dumps(scan_ids),
        summary=summary,
        payload_json=payload_json,
        prompt_context_json=prompt_context_json,
        model_provider=model_provider,
        model_name=model_name,
    )
    session.add(insight)
    session.flush()
    return insight


def llm_memory_dataframe(session: Session, user_id: int) -> pd.DataFrame:
    """Return LLM memory rows as a pandas DataFrame."""

    query = text(
        """
        SELECT id, user_id, date, context_summary, recommendations,
               fatigue_flag, confidence_score
        FROM llm_memory
        WHERE user_id = :user_id
        ORDER BY date DESC
        """
    )
    df = pd.read_sql_query(query, session.bind, params={"user_id": user_id})
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def goals_dataframe(session: Session, user_id: int) -> pd.DataFrame:
    """Return user goals as a dataframe."""

    query = text(
        """
        SELECT id, user_id, name, goal_type, target_distance_km, target_time_minutes,
               target_date, priority, status, is_active, notes, created_at, updated_at
        FROM goals
        WHERE user_id = :user_id
        ORDER BY is_active DESC, target_date ASC, created_at DESC
        """
    )
    df = pd.read_sql_query(query, session.bind, params={"user_id": user_id})
    if not df.empty:
        for column in ("target_date", "created_at", "updated_at"):
            df[column] = pd.to_datetime(df[column])
    return df


def coaching_decisions_dataframe(session: Session, user_id: int) -> pd.DataFrame:
    """Return stored coaching decisions as a dataframe."""

    query = text(
        """
        SELECT id, user_id, goal_id, decision_type, decision_date, summary, risk_level,
               payload_json, email_subject, email_body, created_at
        FROM coaching_decisions
        WHERE user_id = :user_id
        ORDER BY decision_date DESC, created_at DESC
        """
    )
    df = pd.read_sql_query(query, session.bind, params={"user_id": user_id})
    if not df.empty:
        for column in ("decision_date", "created_at"):
            df[column] = pd.to_datetime(df[column])
    return df


def email_deliveries_dataframe(session: Session, user_id: int) -> pd.DataFrame:
    """Return outbound email history as a dataframe."""

    query = text(
        """
        SELECT id, user_id, coaching_decision_id, recipient, subject, status,
               provider_message, sent_at
        FROM email_deliveries
        WHERE user_id = :user_id
        ORDER BY sent_at DESC
        """
    )
    df = pd.read_sql_query(query, session.bind, params={"user_id": user_id})
    if not df.empty:
        df["sent_at"] = pd.to_datetime(df["sent_at"])
    return df


def store_llm_memory(
    session: Session,
    user_id: int,
    context_summary: str,
    recommendations: str,
    fatigue_flag: bool,
    confidence_score: float | None,
) -> LLMMemory:
    """Persist a generated coaching recommendation."""

    memory = LLMMemory(
        user_id=user_id,
        date=datetime.utcnow(),
        context_summary=context_summary,
        recommendations=recommendations,
        fatigue_flag=fatigue_flag,
        confidence_score=confidence_score,
    )
    session.add(memory)
    session.flush()
    return memory


def store_coaching_decision(
    session: Session,
    user_id: int,
    goal_id: int | None,
    decision_type: str,
    decision_date: date,
    summary: str,
    risk_level: str,
    payload_json: str,
    email_subject: str | None,
    email_body: str | None,
) -> CoachingDecision:
    """Persist one structured coaching decision."""

    decision = CoachingDecision(
        user_id=user_id,
        goal_id=goal_id,
        decision_type=decision_type,
        decision_date=decision_date,
        summary=summary,
        risk_level=risk_level,
        payload_json=payload_json,
        email_subject=email_subject,
        email_body=email_body,
    )
    session.add(decision)
    session.flush()
    return decision


def store_email_delivery(
    session: Session,
    user_id: int,
    coaching_decision_id: int | None,
    recipient: str,
    subject: str,
    status: str,
    provider_message: str | None,
) -> EmailDelivery:
    """Persist one outbound email event."""

    delivery = EmailDelivery(
        user_id=user_id,
        coaching_decision_id=coaching_decision_id,
        recipient=recipient,
        subject=subject,
        status=status,
        provider_message=provider_message,
    )
    session.add(delivery)
    session.flush()
    return delivery


def update_activity_note(session: Session, activity_id: int, note: str) -> None:
    """Store a manual note for an activity."""

    activity = session.get(Activity, activity_id)
    if activity is None:
        raise ValueError(f"Unknown activity id: {activity_id}")
    activity.notes = note.strip() or None
    session.flush()


def _goal_time_to_minutes(goal_time: str | float | int | None) -> float:
    if goal_time is None:
        return 240.0
    if isinstance(goal_time, (float, int)):
        return float(goal_time)
    hours, minutes, seconds = [int(part) for part in str(goal_time).split(":")]
    return hours * 60 + minutes + seconds / 60
