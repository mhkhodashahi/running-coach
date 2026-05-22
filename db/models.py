"""SQLAlchemy models for the marathon coach app."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base."""


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class User(Base):
    """User profile and marathon goal."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str | None] = mapped_column(String(80))
    age: Mapped[int | None] = mapped_column(Integer)
    gender: Mapped[str | None] = mapped_column(String(20))
    weight: Mapped[float | None] = mapped_column(Float)
    height: Mapped[float | None] = mapped_column(Float)
    max_hr: Mapped[int | None] = mapped_column(Integer)
    training_days_per_week: Mapped[int | None] = mapped_column(Integer)
    injury_notes: Mapped[str | None] = mapped_column(Text)
    marathon_goal_time: Mapped[str] = mapped_column(String(16), nullable=False, default="03:59:59")
    marathon_date: Mapped[date | None] = mapped_column(Date)

    activities: Mapped[list[Activity]] = relationship(back_populates="user")
    health_metrics: Mapped[list[HealthMetric]] = relationship(back_populates="user")
    llm_memories: Mapped[list[LLMMemory]] = relationship(back_populates="user")
    goals: Mapped[list[Goal]] = relationship(back_populates="user")
    coaching_decisions: Mapped[list[CoachingDecision]] = relationship(back_populates="user")
    activity_coaching_insights: Mapped[list[ActivityCoachingInsight]] = relationship(back_populates="user")
    prediction_snapshots: Mapped[list[PredictionSnapshot]] = relationship(back_populates="user")
    email_deliveries: Mapped[list[EmailDelivery]] = relationship(back_populates="user")
    body_scans: Mapped[list[BodyScan]] = relationship(back_populates="user")
    body_scan_insights: Mapped[list[BodyScanInsight]] = relationship(back_populates="user")
    nutrition_entries: Mapped[list[NutritionEntry]] = relationship(back_populates="user")


class Activity(Base):
    """Training activity imported from Garmin or CSV."""

    __tablename__ = "activities"
    __table_args__ = (UniqueConstraint("user_id", "external_id", name="uq_activities_user_external"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(64))
    activity_name: Mapped[str | None] = mapped_column(String(160))
    date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    distance: Mapped[float] = mapped_column(Float, nullable=False)
    duration: Mapped[float] = mapped_column(Float, nullable=False)
    pace: Mapped[float | None] = mapped_column(Float)
    avg_hr: Mapped[float | None] = mapped_column(Float)
    max_hr: Mapped[float | None] = mapped_column(Float)
    cadence: Mapped[float | None] = mapped_column(Float)
    elevation: Mapped[float | None] = mapped_column(Float)
    training_effect: Mapped[float | None] = mapped_column(Float)
    aerobic_effect: Mapped[float | None] = mapped_column(Float)
    anaerobic_effect: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="activities")
    track_points: Mapped[list[ActivityTrackPoint]] = relationship(back_populates="activity", cascade="all, delete-orphan")
    laps: Mapped[list[ActivityLap]] = relationship(back_populates="activity", cascade="all, delete-orphan")
    coaching_insights: Mapped[list[ActivityCoachingInsight]] = relationship(back_populates="activity", cascade="all, delete-orphan")
    prediction_snapshots: Mapped[list[PredictionSnapshot]] = relationship(back_populates="activity", cascade="all, delete-orphan")


class ActivityTrackPoint(Base):
    """GPS and metric stream point for one activity."""

    __tablename__ = "activity_track_points"
    __table_args__ = (UniqueConstraint("activity_id", "point_index", name="uq_activity_track_points_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    activity_id: Mapped[int] = mapped_column(ForeignKey("activities.id"), index=True, nullable=False)
    point_index: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime)
    elapsed_seconds: Mapped[float | None] = mapped_column(Float)
    distance_km: Mapped[float | None] = mapped_column(Float)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    elevation: Mapped[float | None] = mapped_column(Float)
    pace: Mapped[float | None] = mapped_column(Float)
    speed: Mapped[float | None] = mapped_column(Float)
    heart_rate: Mapped[float | None] = mapped_column(Float)
    cadence: Mapped[float | None] = mapped_column(Float)

    activity: Mapped[Activity] = relationship(back_populates="track_points")


class ActivityLap(Base):
    """Lap or split data for one activity."""

    __tablename__ = "activity_laps"
    __table_args__ = (UniqueConstraint("activity_id", "lap_index", name="uq_activity_laps_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    activity_id: Mapped[int] = mapped_column(ForeignKey("activities.id"), index=True, nullable=False)
    lap_index: Mapped[int] = mapped_column(Integer, nullable=False)
    lap_type: Mapped[str | None] = mapped_column(String(32))
    start_time: Mapped[datetime | None] = mapped_column(DateTime)
    duration: Mapped[float | None] = mapped_column(Float)
    distance: Mapped[float | None] = mapped_column(Float)
    pace: Mapped[float | None] = mapped_column(Float)
    avg_hr: Mapped[float | None] = mapped_column(Float)
    max_hr: Mapped[float | None] = mapped_column(Float)
    elevation_gain: Mapped[float | None] = mapped_column(Float)
    avg_cadence: Mapped[float | None] = mapped_column(Float)

    activity: Mapped[Activity] = relationship(back_populates="laps")


class HealthMetric(Base):
    """Daily health and recovery metrics."""

    __tablename__ = "health_metrics"
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_health_metrics_user_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    sleep_duration: Mapped[float | None] = mapped_column(Float)
    sleep_score: Mapped[float | None] = mapped_column(Float)
    resting_hr: Mapped[float | None] = mapped_column(Float)
    hrv: Mapped[float | None] = mapped_column(Float)
    stress: Mapped[float | None] = mapped_column(Float)
    body_battery: Mapped[float | None] = mapped_column(Float)
    recovery_time: Mapped[float | None] = mapped_column(Float)
    vo2max: Mapped[float | None] = mapped_column(Float)

    user: Mapped[User] = relationship(back_populates="health_metrics")


class NutritionEntry(Base):
    """Daily calorie and macro log."""

    __tablename__ = "nutrition_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    meal_type: Mapped[str] = mapped_column(String(32), nullable=False, default="meal")
    food_name: Mapped[str] = mapped_column(String(120), nullable=False)
    calories: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    protein_g: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    carbs_g: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fat_g: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    user: Mapped[User] = relationship(back_populates="nutrition_entries")


class BodyScan(Base):
    """Body progress photo and optional 3D output metadata."""

    __tablename__ = "body_scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    scan_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    view: Mapped[str] = mapped_column(String(32), nullable=False, default="front")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="uploaded")
    source_image_path: Mapped[str | None] = mapped_column(Text)
    preview_image_path: Mapped[str | None] = mapped_column(Text)
    mesh_path: Mapped[str | None] = mapped_column(Text)
    keypoints_json: Mapped[str | None] = mapped_column(Text)
    measurements_json: Mapped[str | None] = mapped_column(Text)
    pose_quality: Mapped[float | None] = mapped_column(Float)
    processor_name: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    consent_to_store_image: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    user: Mapped[User] = relationship(back_populates="body_scans")


class BodyScanInsight(Base):
    """Stored LLM interpretation of body scan history."""

    __tablename__ = "body_scan_insights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    insight_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    scan_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_context_json: Mapped[str] = mapped_column(Text, nullable=False)
    model_provider: Mapped[str | None] = mapped_column(String(32))
    model_name: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    user: Mapped[User] = relationship(back_populates="body_scan_insights")


class LLMMemory(Base):
    """Stored LLM coaching outputs."""

    __tablename__ = "llm_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    date: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    context_summary: Mapped[str] = mapped_column(Text, nullable=False)
    recommendations: Mapped[str] = mapped_column(Text, nullable=False)
    fatigue_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confidence_score: Mapped[float | None] = mapped_column(Float)

    user: Mapped[User] = relationship(back_populates="llm_memories")


class ActivityCoachingInsight(Base):
    """Stored LLM coach opinion for one activity."""

    __tablename__ = "activity_coaching_insights"
    __table_args__ = (UniqueConstraint("activity_id", name="uq_activity_coaching_insights_activity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    activity_id: Mapped[int] = mapped_column(ForeignKey("activities.id"), index=True, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_context_json: Mapped[str] = mapped_column(Text, nullable=False)
    model_provider: Mapped[str | None] = mapped_column(String(32))
    model_name: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    user: Mapped[User] = relationship(back_populates="activity_coaching_insights")
    activity: Mapped[Activity] = relationship(back_populates="coaching_insights")


class PredictionSnapshot(Base):
    """Stored prediction after an activity/import event."""

    __tablename__ = "prediction_snapshots"
    __table_args__ = (UniqueConstraint("activity_id", "goal_id", name="uq_prediction_snapshots_activity_goal"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    activity_id: Mapped[int | None] = mapped_column(ForeignKey("activities.id"), index=True)
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("goals.id"), index=True)
    prediction_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    race_distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    predicted_time_minutes: Mapped[float] = mapped_column(Float, nullable=False)
    predicted_pace: Mapped[float] = mapped_column(Float, nullable=False)
    gap_minutes: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    user: Mapped[User] = relationship(back_populates="prediction_snapshots")
    activity: Mapped[Activity | None] = relationship(back_populates="prediction_snapshots")
    goal: Mapped[Goal | None] = relationship(back_populates="prediction_snapshots")


class Goal(Base):
    """Athlete goal such as 5k PB or marathon PB."""

    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    goal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    target_time_minutes: Mapped[float] = mapped_column(Float, nullable=False)
    target_date: Mapped[date | None] = mapped_column(Date)
    priority: Mapped[str] = mapped_column(String(8), nullable=False, default="A")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    user: Mapped[User] = relationship(back_populates="goals")
    coaching_decisions: Mapped[list[CoachingDecision]] = relationship(back_populates="goal")
    prediction_snapshots: Mapped[list[PredictionSnapshot]] = relationship(back_populates="goal")


class CoachingDecision(Base):
    """Structured daily or weekly coaching decision."""

    __tablename__ = "coaching_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("goals.id"), index=True)
    decision_type: Mapped[str] = mapped_column(String(16), nullable=False)
    decision_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="moderate")
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    email_subject: Mapped[str | None] = mapped_column(Text)
    email_body: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    user: Mapped[User] = relationship(back_populates="coaching_decisions")
    goal: Mapped[Goal | None] = relationship(back_populates="coaching_decisions")
    email_deliveries: Mapped[list[EmailDelivery]] = relationship(back_populates="coaching_decision")


class EmailDelivery(Base):
    """History of outbound coaching emails."""

    __tablename__ = "email_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    coaching_decision_id: Mapped[int | None] = mapped_column(ForeignKey("coaching_decisions.id"), index=True)
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_message: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    user: Mapped[User] = relationship(back_populates="email_deliveries")
    coaching_decision: Mapped[CoachingDecision | None] = relationship(back_populates="email_deliveries")
