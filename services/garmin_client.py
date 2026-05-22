"""Garmin connector abstractions and CSV implementation."""

from __future__ import annotations

import ast
import json
from abc import ABC, abstractmethod
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO

import pandas as pd
from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

try:
    from garth.exc import GarthHTTPError
except ImportError:  # garminconnect 0.3.x no longer depends on garth.
    class GarthHTTPError(Exception):
        """Compatibility placeholder for older garth-backed login failures."""


def _coerce_numeric(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_activity_type(raw_value: Any) -> str:
    if raw_value is None:
        return "unknown"
    if isinstance(raw_value, str):
        stripped = raw_value.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                parsed = ast.literal_eval(stripped)
                if isinstance(parsed, dict):
                    return str(parsed.get("typeKey", "unknown"))
            except (SyntaxError, ValueError):
                pass
        return stripped.lower()
    if isinstance(raw_value, dict):
        return str(raw_value.get("typeKey", "unknown"))
    return str(raw_value).lower()


def _normalize_distance(distance: float | None) -> float:
    if distance is None:
        return 0.0
    return distance / 1000 if distance > 100 else distance


def _normalize_duration(duration: float | None) -> float:
    if duration is None:
        return 0.0
    return duration / 60 if duration > 300 else duration


def _safe_date(value: Any) -> date | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def _safe_datetime(value: Any) -> datetime | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def _dict_path(data: Any, *path: str) -> Any:
    current = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _walk_dicts(data: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if isinstance(data, dict):
        items.append(data)
        for value in data.values():
            items.extend(_walk_dicts(value))
    elif isinstance(data, list):
        for value in data:
            items.extend(_walk_dicts(value))
    return items


def _walk_lists(data: Any) -> list[list[Any]]:
    items: list[list[Any]] = []
    if isinstance(data, list):
        items.append(data)
        for value in data:
            items.extend(_walk_lists(value))
    elif isinstance(data, dict):
        for value in data.values():
            items.extend(_walk_lists(value))
    return items


def _flatten_candidate_values(data: Any, key_names: set[str]) -> list[float]:
    values: list[float] = []
    if isinstance(data, dict):
        for key, value in data.items():
            if key in key_names:
                numeric = _coerce_numeric(value)
                if numeric is not None:
                    values.append(numeric)
            values.extend(_flatten_candidate_values(value, key_names))
    elif isinstance(data, list):
        for item in data:
            values.extend(_flatten_candidate_values(item, key_names))
    return values


def _pick_first_numeric(data: Any, candidates: list[tuple[str, ...]]) -> float | None:
    for candidate in candidates:
        value = _coerce_numeric(_dict_path(data, *candidate))
        if value is not None:
            return value
    return None


def _pick_first_value(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    text = str(value).strip()
    return text or None


def _meters_to_km(value: float | None, *, force_meters: bool = False) -> float | None:
    if value is None:
        return None
    if force_meters:
        return round(value / 1000, 4)
    return round(value / 1000, 4) if value > 100 else round(value, 4)


def _seconds_to_minutes(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value / 60, 3)


def _speed_to_pace(speed: float | None) -> float | None:
    if speed is None or speed <= 0:
        return None
    # Garmin speed is commonly m/s. If the value is already km/h, this still gives a sensible fallback.
    kmh = speed * 3.6 if speed < 20 else speed
    return round(60 / kmh, 3) if kmh > 0 else None


def _normalize_pace(value: float | None, speed: float | None = None) -> float | None:
    """Return pace as minutes per kilometer from Garmin's mixed raw units."""

    if value is None or value <= 0:
        return _speed_to_pace(speed)
    if value <= 60:
        return round(value, 3)

    speed_pace = _speed_to_pace(speed)
    if speed_pace is not None:
        return speed_pace

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


def _semicircles_to_degrees(value: float | None) -> float | None:
    if value is None:
        return None
    if abs(value) > 180:
        return value * (180 / 2**31)
    return value


def _metric_value(metrics: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = _coerce_numeric(metrics.get(name))
        if value is not None:
            return value
    lowered = {str(key).lower(): value for key, value in metrics.items()}
    for name in names:
        value = _coerce_numeric(lowered.get(name.lower()))
        if value is not None:
            return value
    return None


def _extract_descriptor_metrics(details: dict[str, Any]) -> list[dict[str, Any]]:
    descriptors = details.get("metricDescriptors")
    samples = details.get("activityDetailMetrics")
    if not isinstance(descriptors, list) or not isinstance(samples, list):
        return []

    names = [
        str(item.get("key") or item.get("metricKey") or item.get("name") or item.get("displayName") or index)
        for index, item in enumerate(descriptors)
        if isinstance(item, dict)
    ]
    if not names:
        return []

    rows: list[dict[str, Any]] = []
    for sample in samples:
        values = sample.get("metrics") if isinstance(sample, dict) else None
        if not isinstance(values, list):
            continue
        row = {names[index]: values[index] for index in range(min(len(names), len(values)))}
        if isinstance(sample, dict):
            row.update({key: value for key, value in sample.items() if key != "metrics"})
        rows.append(row)
    return rows


def _extract_polyline_points(details: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("geoPolylineDTO", "polyline", "polylineDTO"):
        candidate = details.get(key)
        if isinstance(candidate, dict):
            for nested_key in ("polyline", "points", "geoPolyline"):
                nested = candidate.get(nested_key)
                if isinstance(nested, list):
                    return [item for item in nested if isinstance(item, dict)]
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]

    lists = _walk_lists(details)
    best: list[dict[str, Any]] = []
    for candidate in lists:
        dict_items = [item for item in candidate if isinstance(item, dict)]
        if len(dict_items) > len(best) and any(
            any(key in item for key in ("lat", "latitude", "directLatitude")) for item in dict_items[:5]
        ):
            best = dict_items
    return best


def extract_activity_track_points(details: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract normalized GPS/chart points from a Garmin activity details payload."""

    metric_rows = _extract_descriptor_metrics(details)
    polyline_rows = _extract_polyline_points(details)
    source_rows = metric_rows or polyline_rows
    if not source_rows:
        return []

    rows: list[dict[str, Any]] = []
    for index, row in enumerate(source_rows):
        polyline = polyline_rows[index] if index < len(polyline_rows) else {}
        latitude = _metric_value(row, "directLatitude", "latitude", "lat", "positionLat")
        longitude = _metric_value(row, "directLongitude", "longitude", "lon", "lng", "positionLong")
        if latitude is None:
            latitude = _metric_value(polyline, "directLatitude", "latitude", "lat")
        if longitude is None:
            longitude = _metric_value(polyline, "directLongitude", "longitude", "lon", "lng")

        elapsed_seconds = _metric_value(row, "sumElapsedDuration", "elapsedDuration", "duration", "timerDuration")
        distance_value = _metric_value(row, "sumDistance", "distance", "totalDistance")
        distance_km = _meters_to_km(distance_value, force_meters=any(key in row for key in ("sumDistance", "totalDistance")))
        speed = _metric_value(row, "directSpeed", "speed", "averageSpeed")
        pace = _normalize_pace(_metric_value(row, "pace", "directPace"), speed)

        normalized = {
            "point_index": index,
            "timestamp": _safe_datetime(_pick_first_value(row, ("startTimeGMT", "startTimeLocal", "timestamp", "time"))),
            "elapsed_seconds": elapsed_seconds,
            "distance_km": distance_km,
            "latitude": _semicircles_to_degrees(latitude),
            "longitude": _semicircles_to_degrees(longitude),
            "elevation": _metric_value(row, "directElevation", "elevation", "altitude"),
            "pace": pace,
            "speed": speed,
            "heart_rate": _metric_value(row, "directHeartRate", "heartRate", "heart_rate"),
            "cadence": _metric_value(row, "directRunCadence", "runCadence", "cadence"),
        }
        if any(value is not None for key, value in normalized.items() if key != "point_index"):
            rows.append(normalized)
    return rows


def _extract_lap_items(splits_payload: Any) -> list[dict[str, Any]]:
    if isinstance(splits_payload, list):
        return [item for item in splits_payload if isinstance(item, dict)]
    if not isinstance(splits_payload, dict):
        return []

    for key in ("lapDTOs", "splits", "splitDTOs", "activitySplits", "lapSplits", "typedSplits"):
        value = splits_payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    candidates = []
    for item in _walk_lists(splits_payload):
        dict_items = [value for value in item if isinstance(value, dict)]
        if len(dict_items) > len(candidates) and any(
            any(key in value for key in ("distance", "duration", "splitType", "startTimeGMT")) for value in dict_items[:5]
        ):
            candidates = dict_items
    return candidates


def extract_activity_laps(*payloads: Any) -> list[dict[str, Any]]:
    """Extract normalized laps/splits from Garmin split payloads."""

    items: list[dict[str, Any]] = []
    for payload in payloads:
        items = _extract_lap_items(payload)
        if items:
            break
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        distance = _meters_to_km(_metric_value(item, "distance", "totalDistance", "splitDistance"))
        duration = _seconds_to_minutes(_metric_value(item, "duration", "elapsedDuration", "movingDuration", "timerDuration"))
        pace = _metric_value(item, "pace", "averagePace")
        if pace is None and distance and duration:
            pace = round(duration / distance, 3)

        row = {
            "lap_index": int(_coerce_numeric(item.get("lapIndex") or item.get("splitIndex") or item.get("splitNumber")) or index),
            "lap_type": str(item.get("splitType") or item.get("lapType") or item.get("type") or "lap"),
            "start_time": _safe_datetime(_pick_first_value(item, ("startTimeGMT", "startTimeLocal", "startTime", "beginTimestamp"))),
            "duration": duration,
            "distance": distance,
            "pace": pace,
            "avg_hr": _metric_value(item, "averageHR", "avgHr", "averageHeartRate", "avg_heart_rate"),
            "max_hr": _metric_value(item, "maxHR", "maxHr", "maxHeartRate"),
            "elevation_gain": _metric_value(item, "elevationGain", "totalAscent", "ascent"),
            "avg_cadence": _metric_value(item, "averageRunCadence", "averageCadence", "avgCadence"),
        }
        if any(value is not None for key, value in row.items() if key not in {"lap_index", "lap_type"}):
            rows.append(row)
    return rows


def _extract_sleep_duration_hours(sleep_data: dict[str, Any]) -> float | None:
    seconds = _pick_first_numeric(
        sleep_data,
        [
            ("dailySleepDTO", "sleepTimeSeconds"),
            ("dailySleepDTO", "sleepTimeSecondsLocalized"),
            ("sleepTimeSeconds",),
        ],
    )
    if seconds is None:
        return None
    return round(seconds / 3600, 2)


def _extract_sleep_score(sleep_data: dict[str, Any]) -> float | None:
    direct = _pick_first_numeric(
        sleep_data,
        [
            ("sleepScores", "overall", "value"),
            ("dailySleepDTO", "sleepScores", "overall", "value"),
            ("sleepScore",),
        ],
    )
    if direct is not None:
        return direct
    values = _flatten_candidate_values(sleep_data, {"overallScore", "sleepScore", "value"})
    return values[0] if values else None


def _extract_body_battery_value(body_battery_data: Any) -> float | None:
    values = _flatten_candidate_values(
        body_battery_data,
        {"bodyBattery", "bodyBatteryValue", "charged", "value", "bodyBatteryCharged"},
    )
    if not values:
        return None
    return round(float(pd.Series(values).median()), 1)


def _extract_hrv_value(hrv_data: Any) -> float | None:
    direct = _pick_first_numeric(
        hrv_data,
        [
            ("hrvSummary", "lastNightAvg"),
            ("lastNightAvg",),
            ("weeklyAvg",),
            ("baseline",),
        ],
    )
    if direct is not None:
        return direct
    values = _flatten_candidate_values(
        hrv_data,
        {"lastNightAvg", "weeklyAvg", "avgOvernightHrv", "hrvValue", "value"},
    )
    if not values:
        return None
    return round(float(pd.Series(values).median()), 1)


def _extract_vo2max_value(max_metrics_data: Any) -> float | None:
    if isinstance(max_metrics_data, list):
        for entry in max_metrics_data:
            value = _coerce_numeric(entry.get("generic")) if isinstance(entry, dict) else None
            if value is not None:
                return value
    direct = _pick_first_numeric(
        max_metrics_data,
        [("generic",), ("vo2MaxPreciseValue",), ("value",)],
    )
    if direct is not None:
        return direct
    values = _flatten_candidate_values(
        max_metrics_data,
        {"generic", "vo2MaxPreciseValue", "vO2MaxValue", "value"},
    )
    return values[0] if values else None


def _normalize_recovery_time_to_hours(value: float | None) -> float | None:
    if value is None:
        return None
    numeric = float(value)
    if numeric < 0:
        return None
    if numeric <= 120:
        return round(numeric, 1)
    if numeric <= 24 * 60 * 8:
        return round(numeric / 60, 1)
    if numeric <= 24 * 60 * 60 * 8:
        return round(numeric / 3600, 1)
    return round(numeric / (3600 * 1000), 1)


def _extract_recovery_time_hours(*payloads: Any) -> float | None:
    candidates = [
        ("recoveryTime",),
        ("latestRecoveryTime",),
        ("monitoringTrainingLoad", "recoveryTime"),
        ("trainingReadinessContribution", "recoveryTime"),
        ("recoveryTimeSummary", "recoveryTime"),
        ("recoveryTimeFactor", "value"),
        ("metrics", "recoveryTime"),
    ]
    for payload in payloads:
        direct = _pick_first_numeric(payload, candidates)
        normalized = _normalize_recovery_time_to_hours(direct)
        if normalized is not None:
            return normalized

        flattened = _flatten_candidate_values(
            payload,
            {
                "recoveryTime",
                "latestRecoveryTime",
                "recoveryTimeSeconds",
                "recoveryTimeInSeconds",
                "recoveryTimeMilliseconds",
                "recoveryTimeMillis",
                "recoveryHours",
                "recoveryTimeHours",
            },
        )
        for value in flattened:
            normalized = _normalize_recovery_time_to_hours(value)
            if normalized is not None:
                return normalized
    return None


def _status_code_from_exception(exc: Exception) -> int | None:
    candidates = [exc]
    visited: set[int] = set()

    while candidates:
        current = candidates.pop(0)
        if current is None:
            continue

        current_id = id(current)
        if current_id in visited:
            continue
        visited.add(current_id)

        response = getattr(current, "response", None)
        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int):
            return status_code

        error = getattr(current, "error", None)
        if isinstance(error, BaseException):
            candidates.append(error)

        cause = getattr(current, "__cause__", None)
        if isinstance(cause, BaseException):
            candidates.append(cause)

        context = getattr(current, "__context__", None)
        if isinstance(context, BaseException):
            candidates.append(context)

    message = " ".join(str(candidate).lower() for candidate in visited_exceptions(exc))
    if "429" in message or "too many requests" in message or "rate limit" in message:
        return 429
    if "401" in message or "unauthorized" in message or "authentication" in message:
        return 401
    return None


def _retry_after_delta(exc: Exception) -> timedelta | None:
    for current in visited_exceptions(exc):
        response = getattr(current, "response", None)
        headers = getattr(response, "headers", None) or {}
        retry_after = headers.get("Retry-After")
        if retry_after and str(retry_after).isdigit():
            return timedelta(seconds=int(retry_after))
    return None


def visited_exceptions(exc: Exception) -> list[BaseException]:
    items: list[BaseException] = []
    queue: list[BaseException] = [exc]
    seen: set[int] = set()

    while queue:
        current = queue.pop(0)
        current_id = id(current)
        if current_id in seen:
            continue
        seen.add(current_id)
        items.append(current)

        error = getattr(current, "error", None)
        if isinstance(error, BaseException):
            queue.append(error)

        cause = getattr(current, "__cause__", None)
        if isinstance(cause, BaseException):
            queue.append(cause)

        context = getattr(current, "__context__", None)
        if isinstance(context, BaseException):
            queue.append(context)

    return items


class GarminClient(ABC):
    """Abstract Garmin data source."""

    @abstractmethod
    def load_activities(self, source: str | Path | BinaryIO, user_id: int) -> list[dict[str, Any]]:
        """Load activity rows from a source."""

    @abstractmethod
    def load_health_metrics(self, source: str | Path | BinaryIO, user_id: int) -> list[dict[str, Any]]:
        """Load health metric rows from a source."""

    def sync_recent_data(self, user_id: int, days: int, health_days: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Sync recent data directly from Garmin when supported."""

        raise NotImplementedError("This Garmin client does not support direct sync.")

    def sync_activity_details(
        self,
        user_id: int,
        activity_rows: list[dict[str, Any]],
    ) -> dict[str, dict[str, list[dict[str, Any]]]]:
        """Sync GPS stream points and laps for activities when supported."""

        raise NotImplementedError("This Garmin client does not support activity detail sync.")


class CSVGarminClient(GarminClient):
    """CSV-based Garmin importer."""

    def load_activities(self, source: str | Path | BinaryIO, user_id: int) -> list[dict[str, Any]]:
        df = pd.read_csv(source)
        if df.empty:
            return []

        date_series = pd.to_datetime(
            df.get("date", df.get("startTimeLocal", df.get("start_time"))),
            errors="coerce",
        )

        records: list[dict[str, Any]] = []
        for index, row in df.iterrows():
            external_id = row.get("external_id", row.get("activityId", index + 1))
            row_distance = _normalize_distance(_coerce_numeric(row.get("distance")))
            row_duration = _normalize_duration(_coerce_numeric(row.get("duration")))
            row_pace = _coerce_numeric(row.get("pace"))
            if row_pace is None and row_distance > 0:
                row_pace = row_duration / row_distance

            parsed_date = date_series.iloc[index]
            if pd.isna(parsed_date):
                continue

            records.append(
                {
                    "user_id": user_id,
                    "external_id": str(external_id),
                    "activity_name": _clean_text(
                        row.get("activity_name", row.get("activityName", row.get("name", row.get("title"))))
                    ),
                    "date": parsed_date.date(),
                    "type": _parse_activity_type(row.get("type", row.get("activityType", row.get("activity_type")))),
                    "distance": round(row_distance, 2),
                    "duration": round(row_duration, 2),
                    "pace": round(row_pace, 2) if row_pace is not None else None,
                    "avg_hr": _coerce_numeric(row.get("avg_hr", row.get("averageHR"))),
                    "max_hr": _coerce_numeric(row.get("max_hr", row.get("maxHR"))),
                    "cadence": _coerce_numeric(
                        row.get("cadence", row.get("averageRunningCadenceInStepsPerMinute"))
                    ),
                    "elevation": _coerce_numeric(row.get("elevation", row.get("elevationGain"))),
                    "training_effect": _coerce_numeric(
                        row.get("training_effect", row.get("activityTrainingLoad"))
                    ),
                    "aerobic_effect": _coerce_numeric(
                        row.get("aerobic_effect", row.get("aerobicTrainingEffect"))
                    ),
                    "anaerobic_effect": _coerce_numeric(
                        row.get("anaerobic_effect", row.get("anaerobicTrainingEffect"))
                    ),
                    "notes": row.get("notes"),
                }
            )
        return records

    def load_health_metrics(self, source: str | Path | BinaryIO, user_id: int) -> list[dict[str, Any]]:
        df = pd.read_csv(source)
        if df.empty:
            return []

        date_series = pd.to_datetime(df.get("date"), errors="coerce")
        records: list[dict[str, Any]] = []
        for index, row in df.iterrows():
            parsed_date = date_series.iloc[index]
            if pd.isna(parsed_date):
                continue

            records.append(
                {
                    "user_id": user_id,
                    "date": parsed_date.date(),
                    "sleep_duration": _coerce_numeric(row.get("sleep_duration", row.get("sleepDurationHours"))),
                    "sleep_score": _coerce_numeric(row.get("sleep_score")),
                    "resting_hr": _coerce_numeric(row.get("resting_hr", row.get("restingHeartRate"))),
                    "hrv": _coerce_numeric(row.get("hrv")),
                    "stress": _coerce_numeric(row.get("stress")),
                    "body_battery": _coerce_numeric(row.get("body_battery", row.get("bodyBattery"))),
                    "recovery_time": _coerce_numeric(row.get("recovery_time", row.get("recoveryTime"))),
                    "vo2max": _coerce_numeric(row.get("vo2max", row.get("vO2MaxValue"))),
                }
            )
        return records

    def sync_activity_details(
        self,
        user_id: int,
        activity_rows: list[dict[str, Any]],
    ) -> dict[str, dict[str, list[dict[str, Any]]]]:
        return {}


class FutureGarminAPIClient(GarminClient):
    """Placeholder API connector for future Garmin integrations."""

    def load_activities(self, source: str | Path | BinaryIO, user_id: int) -> list[dict[str, Any]]:
        raise NotImplementedError("API connector is reserved for a future Garmin integration.")

    def load_health_metrics(self, source: str | Path | BinaryIO, user_id: int) -> list[dict[str, Any]]:
        raise NotImplementedError("API connector is reserved for a future Garmin integration.")


class GarminAPIClient(GarminClient):
    """Live Garmin Connect client using username and password from configuration."""

    def __init__(
        self,
        email: str,
        password: str,
        token_dir: str | Path | None = None,
        rate_limit_cooldown_minutes: int = 30,
    ) -> None:
        if not email or not password:
            raise ValueError("GARMIN_EMAIL and GARMIN_PASSWORD must be configured for live sync.")
        self.email = email
        self.password = password
        self.token_dir = Path(token_dir).resolve() if token_dir else None
        self.rate_limit_cooldown = timedelta(minutes=max(rate_limit_cooldown_minutes, 1))
        self._client: Garmin | None = None

    def _token_store_files_exist(self) -> bool:
        if self.token_dir is None:
            return False
        return any(
            (self.token_dir / filename).exists()
            for filename in ("garmin_tokens.json", "oauth1_token.json", "oauth2_token.json")
        )

    def _rate_limit_path(self) -> Path | None:
        if self.token_dir is None:
            return None
        return self.token_dir / "rate_limit.json"

    def _ensure_token_dir(self) -> None:
        if self.token_dir is not None:
            self.token_dir.mkdir(parents=True, exist_ok=True)

    def _clear_rate_limit(self) -> None:
        rate_limit_path = self._rate_limit_path()
        if rate_limit_path and rate_limit_path.exists():
            rate_limit_path.unlink()

    def _clear_token_store(self) -> None:
        if self.token_dir is None:
            return
        for filename in ("garmin_tokens.json", "oauth1_token.json", "oauth2_token.json"):
            token_file = self.token_dir / filename
            if token_file.exists():
                token_file.unlink()

    def _read_rate_limit_deadline(self) -> datetime | None:
        rate_limit_path = self._rate_limit_path()
        if rate_limit_path is None or not rate_limit_path.exists():
            return None
        try:
            payload = json.loads(rate_limit_path.read_text())
            raw_retry_after = payload.get("retry_after")
            if not raw_retry_after:
                return None
            deadline = datetime.fromisoformat(raw_retry_after)
            return deadline if deadline.tzinfo else deadline.replace(tzinfo=UTC)
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def _guard_rate_limit(self) -> None:
        deadline = self._read_rate_limit_deadline()
        if deadline is None:
            return

        now = datetime.now(UTC)
        if deadline <= now:
            self._clear_rate_limit()
            return

        local_deadline = deadline.astimezone()
        raise RuntimeError(
            "Garmin sign-in is temporarily rate-limited. "
            f"Wait until {local_deadline.strftime('%Y-%m-%d %H:%M %Z')} before retrying."
        )

    def _record_rate_limit(self, exc: Exception) -> None:
        rate_limit_path = self._rate_limit_path()
        if rate_limit_path is None:
            return

        self._ensure_token_dir()
        retry_after = _retry_after_delta(exc) or self.rate_limit_cooldown
        deadline = datetime.now(UTC) + retry_after
        payload = {"retry_after": deadline.isoformat()}
        rate_limit_path.write_text(json.dumps(payload))

    def _persist_tokens(self, client: Garmin) -> None:
        if self.token_dir is None:
            return
        self._ensure_token_dir()
        native_client = getattr(client, "client", None)
        native_dump = getattr(native_client, "dump", None)
        if callable(native_dump):
            native_dump(str(self.token_dir))
            return

        garth_client = getattr(client, "garth", None)
        garth_dump = getattr(garth_client, "dump", None)
        if callable(garth_dump):
            garth_dump(str(self.token_dir))

    def _raise_login_error(self, exc: Exception) -> None:
        status_code = _status_code_from_exception(exc)
        if status_code == 429:
            self._record_rate_limit(exc)
            deadline = self._read_rate_limit_deadline()
            if deadline is not None:
                local_deadline = deadline.astimezone()
                raise RuntimeError(
                    "Garmin rate limit reached. "
                    f"Wait until {local_deadline.strftime('%Y-%m-%d %H:%M %Z')} before syncing again."
                ) from exc
            raise RuntimeError("Garmin rate limit reached. Wait and try syncing again later.") from exc
        if status_code == 401:
            raise ValueError("Garmin authentication failed. Check GARMIN_EMAIL and GARMIN_PASSWORD.") from exc
        raise RuntimeError("Garmin authentication failed during login.") from exc

    def _login(self, client: Garmin) -> None:
        tokenstore = str(self.token_dir) if self.token_dir is not None else None
        try:
            if tokenstore:
                client.login(tokenstore=tokenstore)
            else:
                client.login()
            self._persist_tokens(client)
            return
        except FileNotFoundError:
            # Older garth-backed versions raise when the token files do not exist yet.
            pass
        except GarminConnectAuthenticationError as exc:
            if _status_code_from_exception(exc) == 429:
                self._raise_login_error(exc)
            if not self._token_store_files_exist():
                self._raise_login_error(exc)
            self._clear_token_store()
        except (GarminConnectTooManyRequestsError, GarthHTTPError) as exc:
            self._raise_login_error(exc)
        except Exception as exc:
            status_code = _status_code_from_exception(exc)
            if status_code == 429:
                self._raise_login_error(exc)
            if status_code == 401 and self._token_store_files_exist():
                self._clear_token_store()
            elif status_code == 401:
                self._raise_login_error(exc)
            else:
                raise RuntimeError("Garmin authentication failed during login.") from exc

        try:
            client.login()
            self._persist_tokens(client)
        except (GarminConnectAuthenticationError, GarminConnectTooManyRequestsError, GarthHTTPError) as retry_exc:
            self._raise_login_error(retry_exc)
        except Exception as retry_exc:
            status_code = _status_code_from_exception(retry_exc)
            if status_code in {401, 429}:
                self._raise_login_error(retry_exc)
            raise RuntimeError("Garmin authentication failed during login.") from retry_exc

    def _raise_mapped_error(self, exc: Exception, *, context: str) -> None:
        status_code = _status_code_from_exception(exc)
        if status_code == 401:
            raise ValueError("Garmin authentication failed. Check GARMIN_EMAIL and GARMIN_PASSWORD.") from exc
        if status_code == 429:
            self._record_rate_limit(exc)
            deadline = self._read_rate_limit_deadline()
            if deadline is not None:
                local_deadline = deadline.astimezone()
                raise RuntimeError(
                    "Garmin rate limit reached. "
                    f"Wait until {local_deadline.strftime('%Y-%m-%d %H:%M %Z')} before syncing again."
                ) from exc
            raise RuntimeError("Garmin rate limit reached. Wait and try syncing again later.") from exc
        raise RuntimeError(f"Could not connect to Garmin Connect while fetching {context}.") from exc

    def _call_api(self, request, *, default: Any, context: str, suppress_errors: bool) -> Any:
        try:
            return request()
        except (GarminConnectTooManyRequestsError, GarthHTTPError) as exc:
            self._raise_mapped_error(exc, context=context)
        except GarminConnectAuthenticationError as exc:
            status_code = _status_code_from_exception(exc)
            if status_code == 429:
                self._raise_mapped_error(exc, context=context)
            raise ValueError("Garmin authentication failed. Check GARMIN_EMAIL and GARMIN_PASSWORD.") from exc
        except GarminConnectConnectionError as exc:
            if suppress_errors:
                return default
            raise RuntimeError(f"Could not connect to Garmin Connect while fetching {context}.") from exc
        except Exception as exc:
            status_code = _status_code_from_exception(exc)
            if status_code in {401, 429}:
                self._raise_mapped_error(exc, context=context)
            if suppress_errors:
                return default
            raise RuntimeError(f"Garmin request failed while fetching {context}.") from exc

    def _get_client(self) -> Garmin:
        if self._client is not None:
            return self._client

        self._guard_rate_limit()
        client = Garmin(self.email, self.password)
        print("Logging in to Garmin Connect...")
        try:
            self._login(client)
        except GarminConnectAuthenticationError as exc:
            status_code = _status_code_from_exception(exc)
            if status_code == 429:
                self._raise_mapped_error(exc, context="sign-in")
            raise ValueError("Garmin authentication failed. Check GARMIN_EMAIL and GARMIN_PASSWORD.") from exc
        except GarminConnectTooManyRequestsError as exc:
            self._raise_mapped_error(exc, context="sign-in")
        except GarminConnectConnectionError as exc:
            raise RuntimeError("Could not connect to Garmin Connect.") from exc
        except GarthHTTPError as exc:
            self._raise_mapped_error(exc, context="sign-in")
        except Exception as exc:
            status_code = _status_code_from_exception(exc)
            if status_code in {401, 429}:
                self._raise_mapped_error(exc, context="sign-in")
            raise RuntimeError("Could not connect to Garmin Connect.") from exc

        self._persist_tokens(client)
        self._clear_rate_limit()
        self._client = client
        return client

    def get_authenticated_client(self) -> Garmin:
        """Return an authenticated Garmin client, reusing cached tokens when available."""

        return self._get_client()

    def load_activities(self, source: str | Path | BinaryIO, user_id: int) -> list[dict[str, Any]]:
        raise NotImplementedError("Use sync_recent_data for the live Garmin connector.")

    def load_health_metrics(self, source: str | Path | BinaryIO, user_id: int) -> list[dict[str, Any]]:
        raise NotImplementedError("Use sync_recent_data for the live Garmin connector.")

    def sync_recent_data(self, user_id: int, days: int, health_days: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        client = self._get_client()
        today = date.today()
        activities_start = today - timedelta(days=max(days - 1, 0))
        activities_raw = self._call_api(
            lambda: client.get_activities_by_date(
                activities_start.strftime("%Y-%m-%d"),
                today.strftime("%Y-%m-%d"),
            ),
            default=[],
            context="activities",
            suppress_errors=False,
        )

        activity_rows: list[dict[str, Any]] = []
        for row in activities_raw:
            row_distance = _normalize_distance(_coerce_numeric(row.get("distance")))
            row_duration = _normalize_duration(_coerce_numeric(row.get("duration")))
            row_pace = row_duration / row_distance if row_distance > 0 else None
            activity_date = _safe_date(row.get("startTimeLocal") or row.get("startTimeGMT"))
            if activity_date is None:
                continue

            activity_rows.append(
                {
                    "user_id": user_id,
                    "external_id": str(row.get("activityId") or ""),
                    "activity_name": _clean_text(row.get("activityName") or row.get("activityNameOriginal")),
                    "date": activity_date,
                    "type": _parse_activity_type(row.get("activityType")),
                    "distance": round(row_distance, 2),
                    "duration": round(row_duration, 2),
                    "pace": round(row_pace, 2) if row_pace is not None else None,
                    "avg_hr": _coerce_numeric(row.get("averageHR")),
                    "max_hr": _coerce_numeric(row.get("maxHR")),
                    "cadence": _coerce_numeric(row.get("averageRunningCadenceInStepsPerMinute")),
                    "elevation": _coerce_numeric(row.get("elevationGain")),
                    "training_effect": _coerce_numeric(row.get("activityTrainingLoad")),
                    "aerobic_effect": _coerce_numeric(row.get("aerobicTrainingEffect")),
                    "anaerobic_effect": _coerce_numeric(row.get("anaerobicTrainingEffect")),
                    "notes": None,
                }
            )

        health_rows: list[dict[str, Any]] = []
        health_start = today - timedelta(days=max(health_days - 1, 0))
        for offset in range((today - health_start).days + 1):
            current_day = health_start + timedelta(days=offset)
            current_day_str = current_day.strftime("%Y-%m-%d")
            stats = self._call_api(
                lambda current_day_str=current_day_str: client.get_stats(current_day_str) or {},
                default={},
                context=f"stats for {current_day_str}",
                suppress_errors=True,
            )
            sleep = self._call_api(
                lambda current_day_str=current_day_str: client.get_sleep_data(current_day_str) or {},
                default={},
                context=f"sleep data for {current_day_str}",
                suppress_errors=True,
            )
            body_battery = self._call_api(
                lambda current_day_str=current_day_str: client.get_body_battery(current_day_str, current_day_str) or [],
                default=[],
                context=f"body battery for {current_day_str}",
                suppress_errors=True,
            )
            hrv = self._call_api(
                lambda current_day_str=current_day_str: client.get_hrv_data(current_day_str) or {},
                default={},
                context=f"HRV data for {current_day_str}",
                suppress_errors=True,
            )
            max_metrics = self._call_api(
                lambda current_day_str=current_day_str: client.get_max_metrics(current_day_str) or {},
                default={},
                context=f"VO2 max data for {current_day_str}",
                suppress_errors=True,
            )
            training_readiness = self._call_api(
                lambda current_day_str=current_day_str: (
                    client.get_morning_training_readiness(current_day_str)
                    or client.get_training_readiness(current_day_str)
                    or {}
                ),
                default={},
                context=f"training readiness for {current_day_str}",
                suppress_errors=True,
            )
            training_status = self._call_api(
                lambda current_day_str=current_day_str: client.get_training_status(current_day_str) or {},
                default={},
                context=f"training status for {current_day_str}",
                suppress_errors=True,
            )

            resting_hr = _pick_first_numeric(
                stats,
                [
                    ("restingHeartRate",),
                    ("restingHR",),
                    ("allMetrics", "metricsMap", "WELLNESS_RESTING_HEART_RATE", "value"),
                ],
            )
            stress = _pick_first_numeric(
                stats,
                [
                    ("averageStressLevel",),
                    ("stressScore",),
                    ("allMetrics", "metricsMap", "WELLNESS_STRESS_SCORE", "value"),
                ],
            )

            row = {
                "user_id": user_id,
                "date": current_day,
                "sleep_duration": _extract_sleep_duration_hours(sleep),
                "sleep_score": _extract_sleep_score(sleep),
                "resting_hr": resting_hr,
                "hrv": _extract_hrv_value(hrv),
                "stress": stress,
                "body_battery": _extract_body_battery_value(body_battery),
                "recovery_time": _extract_recovery_time_hours(
                    training_readiness,
                    training_status,
                    stats,
                ),
                "vo2max": _extract_vo2max_value(max_metrics),
            }
            if any(value is not None for key, value in row.items() if key not in {"user_id", "date"}):
                health_rows.append(row)

        return activity_rows, health_rows

    def sync_activity_details(
        self,
        user_id: int,
        activity_rows: list[dict[str, Any]],
    ) -> dict[str, dict[str, list[dict[str, Any]]]]:
        """Fetch Garmin activity detail streams and split/lap data."""

        client = self._get_client()
        details_by_external_id: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for row in activity_rows:
            external_id = str(row.get("external_id") or "")
            if not external_id:
                continue

            details = self._call_api(
                lambda activity_id=external_id: client.get_activity_details(activity_id) or {},
                default={},
                context=f"activity details for {external_id}",
                suppress_errors=True,
            )
            splits = self._call_api(
                lambda activity_id=external_id: client.get_activity_splits(activity_id) or {},
                default={},
                context=f"activity splits for {external_id}",
                suppress_errors=True,
            )
            split_summaries = self._call_api(
                lambda activity_id=external_id: client.get_activity_split_summaries(activity_id) or {},
                default={},
                context=f"activity split summaries for {external_id}",
                suppress_errors=True,
            )
            typed_splits = self._call_api(
                lambda activity_id=external_id: client.get_activity_typed_splits(activity_id) or {},
                default={},
                context=f"typed activity splits for {external_id}",
                suppress_errors=True,
            )

            track_points = extract_activity_track_points(details if isinstance(details, dict) else {})
            laps = extract_activity_laps(splits, split_summaries, typed_splits)
            if track_points or laps:
                details_by_external_id[external_id] = {
                    "track_points": track_points,
                    "laps": laps,
                }
        return details_by_external_id
