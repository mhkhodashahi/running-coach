"""Persistence reads for bounded, user-scoped coach tools."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


class CoachRepository:
    """Return database records only; fact selection and wording stay in ``coach``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def health_metadata(self, user_id: int, day: date) -> dict[str, Any]:
        latest = self._session.execute(
            text("SELECT MAX(date) FROM health_metrics WHERE user_id=:user_id AND date<=:day"),
            {"user_id": user_id, "day": day.isoformat()},
        ).scalar_one()
        sync = self._session.execute(
            text("SELECT last_synced_at FROM garmin_sync_status WHERE user_id=:user_id"),
            {"user_id": user_id},
        ).scalar_one_or_none()
        return {"latest_health_date": latest, "last_synced_at": sync}

    def health_date_range(self, user_id: int, start: date, end: date) -> tuple[str | None, str | None]:
        row = self._session.execute(
            text("SELECT MIN(date),MAX(date) FROM health_metrics WHERE user_id=:user_id "
                 "AND date BETWEEN :start AND :end"),
            {"user_id": user_id, "start": start.isoformat(), "end": end.isoformat()},
        ).one()
        return row[0], row[1]

    def activity_context(self, user_id: int, activity_id: int, *, lap_limit: int) -> dict[str, Any] | None:
        if lap_limit < 1:
            raise ValueError("lap_limit must be positive")
        activity = self._session.execute(
            text("SELECT id,user_id,date,type,distance,duration,pace,avg_hr,max_hr,aerobic_effect,"
                 "anaerobic_effect,planned_intent,activity_name,notes FROM activities "
                 "WHERE id=:activity_id AND user_id=:user_id"),
            {"activity_id": activity_id, "user_id": user_id},
        ).mappings().first()
        if activity is None:
            return None
        day = str(activity["date"])
        laps = self._rows(
            "SELECT lap_index,distance,duration,pace,avg_hr,max_hr,avg_cadence FROM activity_laps "
            "WHERE activity_id=:activity_id ORDER BY lap_index LIMIT :lap_limit",
            {"activity_id": activity_id, "lap_limit": lap_limit},
        )
        points = self._rows(
            "SELECT elapsed_seconds,distance_km,pace,heart_rate,cadence FROM activity_track_points "
            "WHERE activity_id=:activity_id ORDER BY point_index",
            {"activity_id": activity_id},
        )
        recent_paces = self._session.execute(
            text("SELECT pace FROM activities WHERE user_id=:user_id AND date<=:day AND date>=:since "
                 "AND id!=:activity_id AND pace IS NOT NULL AND lower(type) LIKE '%run%' "
                 "ORDER BY date DESC LIMIT 20"),
            {"user_id": user_id, "day": day,
             "since": (date.fromisoformat(day) - timedelta(days=60)).isoformat(),
             "activity_id": activity_id},
        ).scalars().all()
        effort = self._session.execute(
            text("SELECT rpe FROM activity_efforts WHERE activity_id=:activity_id"),
            {"activity_id": activity_id},
        ).scalar_one_or_none()
        return {"activity": dict(activity), "laps": laps, "points": points,
                "recent_paces": list(recent_paces), "effort_rpe": effort}

    def activity_exists(self, user_id: int, activity_id: int) -> bool:
        return self._session.execute(
            text("SELECT 1 FROM activities WHERE id=:activity_id AND user_id=:user_id"),
            {"activity_id": activity_id, "user_id": user_id},
        ).first() is not None

    def activity_start(self, user_id: int, activity_id: int) -> tuple[float, float] | None:
        row = self._session.execute(
            text("SELECT p.latitude,p.longitude FROM activity_track_points p "
                 "JOIN activities a ON a.id=p.activity_id WHERE a.id=:activity_id AND a.user_id=:user_id "
                 "AND p.latitude IS NOT NULL AND p.longitude IS NOT NULL ORDER BY p.point_index LIMIT 1"),
            {"activity_id": activity_id, "user_id": user_id},
        ).first()
        return (float(row[0]), float(row[1])) if row else None

    def comparison_candidates(
        self, user_id: int, start: date, end: date, measure: str, lower: float, upper: float
    ) -> list[dict[str, Any]]:
        if measure not in {"distance", "duration"}:
            raise ValueError("Unsupported comparison measure")
        rows = self._session.execute(
            text(f"SELECT id,date,type,distance,duration,pace,avg_hr FROM activities "
                 f"WHERE user_id=:user_id AND date>=:start AND date<:end "
                 f"AND {measure} BETWEEN :lower AND :upper ORDER BY date DESC,id DESC"),
            {"user_id": user_id, "start": start.isoformat(), "end": end.isoformat(),
             "lower": lower, "upper": upper},
        ).mappings()
        return [dict(row) for row in rows]

    def activity_rows(self, user_id: int, start: date, end: date) -> list[dict[str, Any]]:
        rows = self._session.execute(
            text("SELECT id,date,type,distance,duration,pace,avg_hr FROM activities "
                 "WHERE user_id=:user_id AND date>=:start AND date<=:end ORDER BY date DESC,id DESC"),
            {"user_id": user_id, "start": start.isoformat(), "end": end.isoformat()},
        ).mappings()
        return [dict(row) for row in rows]

    def recent_activity_cards(self, user_id: int, through: date, limit: int = 120) -> list[dict[str, Any]]:
        rows = self._session.execute(text(
            "SELECT id,date,type,activity_name,duration FROM activities WHERE user_id=:user_id AND date<=:day "
            "ORDER BY date DESC,id DESC LIMIT :limit"),
            {"user_id": user_id, "day": through.isoformat(), "limit": limit}).mappings()
        return [dict(row) for row in rows]

    def activity_card(self, user_id: int, activity_id: int) -> dict[str, Any] | None:
        row = self._session.execute(text(
            "SELECT id,date,type,activity_name FROM activities WHERE id=:activity_id AND user_id=:user_id"),
            {"activity_id": activity_id, "user_id": user_id}).mappings().first()
        return dict(row) if row else None

    def activity_cards(self, user_id: int, activity_ids: list[int]) -> dict[int, dict[str, Any]]:
        if not activity_ids:
            return {}
        placeholders = ",".join(f":id_{index}" for index in range(len(activity_ids)))
        params = {"user_id": user_id, **{f"id_{index}": identifier
                                        for index, identifier in enumerate(activity_ids)}}
        rows = self._session.execute(text(
            "SELECT id,date,type,activity_name FROM activities WHERE user_id=:user_id AND id IN (" +
            placeholders + ")"), params).mappings()
        return {int(row["id"]): dict(row) for row in rows}

    def opinion(self, user_id: int, activity_id: int) -> dict[str, Any] | None:
        row = self._session.execute(
            text("SELECT payload_json,schema_version,prompt_version,model_provider,model_name,created_at "
                 "FROM activity_coaching_insights WHERE activity_id=:activity_id AND user_id=:user_id"),
            {"activity_id": activity_id, "user_id": user_id},
        ).mappings().first()
        return dict(row) if row else None

    def week_plan(self, user_id: int, start: date) -> dict[str, Any]:
        end = start.fromordinal(start.toordinal() + 7)
        version = self._session.execute(
            text("SELECT version FROM plan_versions WHERE user_id=:user_id"),
            {"user_id": user_id},
        ).scalar_one_or_none()
        sessions = self._rows(
            "SELECT date,sport,intent,duration_min,origin,fixed_commitment_id FROM plan_sessions "
            "WHERE user_id=:user_id AND date>=:start AND date<:end ORDER BY date,id LIMIT 30",
            {"user_id": user_id, "start": start.isoformat(), "end": end.isoformat()},
        )
        commitments = self._rows(
            "SELECT id,weekday,sport,kind,typical_duration_min FROM fixed_commitments "
            "WHERE user_id=:user_id AND active=1",
            {"user_id": user_id},
        )
        return {"version": int(version or 0), "sessions": sessions, "commitments": commitments}

    def goals(self, user_id: int) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT id,goal_type,target_distance_km,target_time_minutes,target_date,priority,status,is_active "
            "FROM goals WHERE user_id=:user_id ORDER BY is_active DESC,target_date,id LIMIT 10",
            {"user_id": user_id},
        )

    def recent_efforts(self, user_id: int) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT a.id,a.date,a.type,e.rpe FROM activity_efforts e "
            "JOIN activities a ON a.id=e.activity_id WHERE a.user_id=:user_id "
            "ORDER BY a.date DESC,a.id DESC LIMIT 20",
            {"user_id": user_id},
        )

    def _rows(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        return [dict(row) for row in self._session.execute(text(query), params).mappings()]
