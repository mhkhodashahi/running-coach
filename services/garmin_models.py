"""Validated Garmin import row models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ActivityTrackPointRow(BaseModel):
    """Normalized GPS and metric stream point ready for persistence."""

    model_config = ConfigDict(extra="forbid")

    point_index: int = Field(ge=0)
    timestamp: datetime | None = None
    elapsed_seconds: float | None = Field(default=None, ge=0)
    distance_km: float | None = Field(default=None, ge=0)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    elevation: float | None = None
    pace: float | None = Field(default=None, ge=0)
    speed: float | None = Field(default=None, ge=0)
    heart_rate: float | None = Field(default=None, ge=0)
    cadence: float | None = Field(default=None, ge=0)

    @model_validator(mode="before")
    @classmethod
    def normalize_raw_pace(cls, data):
        if not isinstance(data, dict):
            return data
        value = data.get("pace")
        if value is None:
            return data
        try:
            pace = float(value)
        except (TypeError, ValueError):
            return data
        if 0 <= pace <= 60:
            return data

        speed = data.get("speed")
        try:
            speed_value = float(speed) if speed is not None else None
        except (TypeError, ValueError):
            speed_value = None
        normalized = _normalize_pace_value(pace, speed_value)
        if normalized is not None:
            data = dict(data)
            data["pace"] = normalized
        return data

    @field_validator("pace")
    @classmethod
    def reject_unrealistic_pace(cls, value: float | None) -> float | None:
        if value is not None and value > 60:
            raise ValueError("pace must be minutes per kilometer, not seconds, seconds per 100m, or milliseconds")
        return value


class ActivityLapRow(BaseModel):
    """Normalized lap or split row ready for persistence."""

    model_config = ConfigDict(extra="forbid")

    lap_index: int = Field(ge=0)
    lap_type: str | None = None
    start_time: datetime | None = None
    duration: float | None = Field(default=None, ge=0)
    distance: float | None = Field(default=None, ge=0)
    pace: float | None = Field(default=None, ge=0)
    avg_hr: float | None = Field(default=None, ge=0)
    max_hr: float | None = Field(default=None, ge=0)
    elevation_gain: float | None = None
    avg_cadence: float | None = Field(default=None, ge=0)

    @field_validator("lap_type")
    @classmethod
    def clean_lap_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().lower()
        return cleaned or None


def validate_track_points(rows: list[dict]) -> list[dict]:
    """Validate and normalize track point dictionaries."""

    return [ActivityTrackPointRow(**row).model_dump() for row in rows]


def validate_laps(rows: list[dict]) -> list[dict]:
    """Validate and normalize lap dictionaries."""

    return [ActivityLapRow(**row).model_dump() for row in rows]


def _normalize_pace_value(value: float, speed: float | None = None) -> float | None:
    if value <= 0:
        return None
    if speed is not None and speed > 0:
        kmh = speed * 3.6 if speed < 20 else speed
        if kmh > 0:
            pace = 60 / kmh
            if 0 <= pace <= 60:
                return round(pace, 3)

    seconds_per_km = value / 60
    if 2 <= seconds_per_km <= 60:
        return round(seconds_per_km, 3)

    seconds_per_100m = value / 6
    if 2 <= seconds_per_100m <= 60:
        return round(seconds_per_100m, 3)

    milliseconds_per_km = value / 60000
    if 2 <= milliseconds_per_km <= 60:
        return round(milliseconds_per_km, 3)

    return None
