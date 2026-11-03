"""Normalize Garmin CSV and live API payloads into repository rows."""

from __future__ import annotations

import ast
import json
from datetime import date, datetime
from typing import Any

import pandas as pd


def coerce_numeric(value: Any) -> float | None:
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


def parse_activity_type(raw_value: Any) -> str:
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


def normalize_distance(distance: float | None) -> float:
    if distance is None:
        return 0.0
    return distance / 1000 if distance > 100 else distance


def normalize_duration(duration: float | None) -> float:
    if duration is None:
        return 0.0
    return duration / 60 if duration > 300 else duration


def safe_date(value: Any) -> date | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def safe_datetime(value: Any) -> datetime | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def extract_activity_exercise_sets(payload: Any) -> list[dict[str, Any]]:
    """Normalize Garmin's active/rest intervals; exercise names are candidates, not certainties."""

    if not isinstance(payload, dict) or not isinstance(payload.get("exerciseSets"), list):
        return []
    rows = []
    for index, item in enumerate(payload["exerciseSets"]):
        if not isinstance(item, dict):
            continue
        set_type = str(item.get("setType") or "UNKNOWN").upper()
        if set_type not in ("ACTIVE", "REST"):
            set_type = "UNKNOWN"
        duration = coerce_numeric(item.get("duration"))
        repetitions = coerce_numeric(item.get("repetitionCount"))
        weight = coerce_numeric(item.get("weight"))
        candidates = []
        for candidate in item.get("exercises") or []:
            if isinstance(candidate, dict):
                candidates.append({key: candidate[key] for key in ("category", "name", "probability")
                                   if key in candidate})
        rows.append({"set_index": index + 1, "set_type": set_type,
                     "start_time": safe_datetime(item.get("startTime")),
                     "duration_seconds": duration if duration is not None and duration >= 0 else None,
                     "repetition_count": int(repetitions) if repetitions is not None and repetitions >= 0 else None,
                     "weight_grams": weight if weight is not None and weight >= 0 else None,
                     "exercises_json": json.dumps(candidates, separators=(",", ":"))})
    return rows


def dict_path(data: Any, *path: str) -> Any:
    current = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def walk_lists(data: Any) -> list[list[Any]]:
    items: list[list[Any]] = []
    if isinstance(data, list):
        items.append(data)
        for value in data:
            items.extend(walk_lists(value))
    elif isinstance(data, dict):
        for value in data.values():
            items.extend(walk_lists(value))
    return items


def flatten_candidate_values(data: Any, key_names: set[str]) -> list[float]:
    values: list[float] = []
    if isinstance(data, dict):
        for key, value in data.items():
            if key in key_names:
                numeric = coerce_numeric(value)
                if numeric is not None:
                    values.append(numeric)
            values.extend(flatten_candidate_values(value, key_names))
    elif isinstance(data, list):
        for item in data:
            values.extend(flatten_candidate_values(item, key_names))
    return values


def pick_first_numeric(data: Any, candidates: list[tuple[str, ...]]) -> float | None:
    for candidate in candidates:
        value = coerce_numeric(dict_path(data, *candidate))
        if value is not None:
            return value
    return None


def pick_first_value(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    text = str(value).strip()
    return text or None


def meters_to_km(value: float | None, *, force_meters: bool = False) -> float | None:
    if value is None:
        return None
    if force_meters:
        return round(value / 1000, 4)
    return round(value / 1000, 4) if value > 100 else round(value, 4)


def seconds_to_minutes(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value / 60, 3)


def speed_to_pace(speed: float | None) -> float | None:
    if speed is None or speed <= 0:
        return None
    kmh = speed * 3.6 if speed < 20 else speed
    return round(60 / kmh, 3) if kmh > 0 else None


def normalize_pace(value: float | None, speed: float | None = None) -> float | None:
    """Return pace as minutes per kilometer from Garmin's mixed raw units."""

    if value is None or value <= 0:
        return speed_to_pace(speed)
    if value <= 60:
        return round(value, 3)

    speed_pace = speed_to_pace(speed)
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


def semicircles_to_degrees(value: float | None) -> float | None:
    if value is None:
        return None
    if abs(value) > 180:
        return value * (180 / 2**31)
    return value


def metric_value(metrics: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = coerce_numeric(metrics.get(name))
        if value is not None:
            return value
    lowered = {str(key).lower(): value for key, value in metrics.items()}
    for name in names:
        value = coerce_numeric(lowered.get(name.lower()))
        if value is not None:
            return value
    return None


def extract_descriptor_metrics(details: dict[str, Any]) -> list[dict[str, Any]]:
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


def extract_polyline_points(details: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("geoPolylineDTO", "polyline", "polylineDTO"):
        candidate = details.get(key)
        if isinstance(candidate, dict):
            for nested_key in ("polyline", "points", "geoPolyline"):
                nested = candidate.get(nested_key)
                if isinstance(nested, list):
                    return [item for item in nested if isinstance(item, dict)]
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]

    lists = walk_lists(details)
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

    metric_rows = extract_descriptor_metrics(details)
    polyline_rows = extract_polyline_points(details)
    source_rows = metric_rows or polyline_rows
    if not source_rows:
        return []

    rows: list[dict[str, Any]] = []
    for index, row in enumerate(source_rows):
        polyline = polyline_rows[index] if index < len(polyline_rows) else {}
        latitude = metric_value(row, "directLatitude", "latitude", "lat", "positionLat")
        longitude = metric_value(row, "directLongitude", "longitude", "lon", "lng", "positionLong")
        if latitude is None:
            latitude = metric_value(polyline, "directLatitude", "latitude", "lat")
        if longitude is None:
            longitude = metric_value(polyline, "directLongitude", "longitude", "lon", "lng")

        elapsed_seconds = metric_value(row, "sumElapsedDuration", "elapsedDuration", "duration", "timerDuration")
        distance_value = metric_value(row, "sumDistance", "distance", "totalDistance")
        distance_km = meters_to_km(distance_value, force_meters=any(key in row for key in ("sumDistance", "totalDistance")))
        speed = metric_value(row, "directSpeed", "speed", "averageSpeed")
        pace = normalize_pace(metric_value(row, "pace", "directPace"), speed)

        normalized = {
            "point_index": index,
            "timestamp": safe_datetime(pick_first_value(row, ("startTimeGMT", "startTimeLocal", "timestamp", "time"))),
            "elapsed_seconds": elapsed_seconds,
            "distance_km": distance_km,
            "latitude": semicircles_to_degrees(latitude),
            "longitude": semicircles_to_degrees(longitude),
            "elevation": metric_value(row, "directElevation", "elevation", "altitude"),
            "pace": pace,
            "speed": speed,
            "heart_rate": metric_value(row, "directHeartRate", "heartRate", "heart_rate"),
            "cadence": metric_value(row, "directRunCadence", "runCadence", "cadence"),
        }
        if any(value is not None for key, value in normalized.items() if key != "point_index"):
            rows.append(normalized)
    return rows


def extract_lap_items(splits_payload: Any) -> list[dict[str, Any]]:
    if isinstance(splits_payload, list):
        return [item for item in splits_payload if isinstance(item, dict)]
    if not isinstance(splits_payload, dict):
        return []

    for key in ("lapDTOs", "splits", "splitDTOs", "activitySplits", "lapSplits", "typedSplits"):
        value = splits_payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    candidates = []
    for item in walk_lists(splits_payload):
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
        items = extract_lap_items(payload)
        if items:
            break
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        distance = meters_to_km(metric_value(item, "distance", "totalDistance", "splitDistance"))
        duration = seconds_to_minutes(metric_value(item, "duration", "elapsedDuration", "movingDuration", "timerDuration"))
        pace = metric_value(item, "pace", "averagePace")
        if pace is None and distance and duration:
            pace = round(duration / distance, 3)

        row = {
            "lap_index": int(coerce_numeric(item.get("lapIndex") or item.get("splitIndex") or item.get("splitNumber")) or index),
            "lap_type": str(item.get("splitType") or item.get("lapType") or item.get("type") or "lap"),
            "start_time": safe_datetime(pick_first_value(item, ("startTimeGMT", "startTimeLocal", "startTime", "beginTimestamp"))),
            "duration": duration,
            "distance": distance,
            "pace": pace,
            "avg_hr": metric_value(item, "averageHR", "avgHr", "averageHeartRate", "avg_heart_rate"),
            "max_hr": metric_value(item, "maxHR", "maxHr", "maxHeartRate"),
            "elevation_gain": metric_value(item, "elevationGain", "totalAscent", "ascent"),
            "avg_cadence": metric_value(item, "averageRunCadence", "averageCadence", "avgCadence"),
        }
        if any(value is not None for key, value in row.items() if key not in {"lap_index", "lap_type"}):
            rows.append(row)
    return rows


def extract_sleep_duration_hours(sleep_data: dict[str, Any]) -> float | None:
    seconds = pick_first_numeric(
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


def extract_sleep_score(sleep_data: dict[str, Any]) -> float | None:
    direct = pick_first_numeric(
        sleep_data,
        [
            ("sleepScores", "overall", "value"),
            ("dailySleepDTO", "sleepScores", "overall", "value"),
            ("sleepScore",),
        ],
    )
    if direct is not None:
        return direct
    values = flatten_candidate_values(sleep_data, {"overallScore", "sleepScore", "value"})
    return values[0] if values else None


def extract_body_battery_value(body_battery_data: Any) -> float | None:
    values = flatten_candidate_values(
        body_battery_data,
        {"bodyBattery", "bodyBatteryValue", "charged", "value", "bodyBatteryCharged"},
    )
    if not values:
        return None
    return round(float(pd.Series(values).median()), 1)


def extract_hrv_value(hrv_data: Any) -> float | None:
    direct = pick_first_numeric(
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
    values = flatten_candidate_values(
        hrv_data,
        {"lastNightAvg", "weeklyAvg", "avgOvernightHrv", "hrvValue", "value"},
    )
    if not values:
        return None
    return round(float(pd.Series(values).median()), 1)


def _garmin_clock(value: Any, timezone: str) -> str | None:
    """Render Garmin's UTC timestamp as the athlete's local clock time."""
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    if value is None:
        return None
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            stamp = float(value)
            if stamp > 1e11:
                stamp /= 1000
            moment = datetime.fromtimestamp(stamp, UTC)
        else:
            moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if moment.tzinfo is None:
                return moment.strftime("%H:%M")
        return moment.astimezone(ZoneInfo(timezone)).strftime("%H:%M")
    except (ValueError, OverflowError):
        return None


def extract_night_details(sleep: dict[str, Any], hrv: dict[str, Any], stats: dict[str, Any],
                          body_battery: Any, timezone: str) -> dict[str, Any]:
    """Extract optional Garmin night fields without guessing missing values."""
    dto = sleep.get("dailySleepDTO") or {}
    summary = hrv.get("hrvSummary") or {}
    baseline = summary.get("baseline") if isinstance(summary.get("baseline"), dict) else {}

    def minutes(*keys: str) -> float | None:
        seconds = pick_first_numeric(sleep, [("dailySleepDTO", key) for key in keys])
        return round(seconds / 60, 1) if seconds is not None else None

    battery_items = body_battery if isinstance(body_battery, list) else [body_battery]
    battery_levels: list[float] = []
    charged: float | None = None
    for item in battery_items:
        if not isinstance(item, dict):
            continue
        direct = pick_first_numeric(item, [("bodyBatteryValue",), ("bodyBattery",), ("value",)])
        if direct is not None:
            battery_levels.append(direct)
        for point in item.get("bodyBatteryValuesArray") or []:
            if isinstance(point, (list, tuple)) and len(point) >= 2:
                value = coerce_numeric(point[1])
                if value is not None:
                    battery_levels.append(value)
        item_charged = pick_first_numeric(item, [("bodyBatteryCharged",), ("charged",)])
        if item_charged is not None:
            charged = item_charged
    start = battery_levels[0] if battery_levels else None
    end = battery_levels[-1] if battery_levels else None
    return {
        "sleep_deep_min": minutes("deepSleepSeconds"),
        "sleep_rem_min": minutes("remSleepSeconds"),
        "sleep_light_min": minutes("lightSleepSeconds"),
        "sleep_awake_min": minutes("awakeSleepSeconds"),
        "sleep_bedtime": _garmin_clock(dto.get("sleepStartTimestampGMT") or dto.get("sleepStartTimestampLocal"),
                                       timezone),
        "sleep_wake_time": _garmin_clock(dto.get("sleepEndTimestampGMT") or dto.get("sleepEndTimestampLocal"),
                                        timezone),
        "sleep_wakeups": coerce_numeric(dto.get("numberOfAwakenings") if
                                        dto.get("numberOfAwakenings") is not None else dto.get("awakeningsCount")),
        "hrv_weekly_avg": pick_first_numeric(hrv, [("hrvSummary", "weeklyAvg"), ("weeklyAvg",)]),
        "hrv_baseline_low": pick_first_numeric(baseline, [("balancedLow",), ("lower",), ("low",)]),
        "hrv_baseline_high": pick_first_numeric(baseline, [("balancedUpper",), ("upper",), ("high",)]),
        "hrv_status": str(summary.get("status") or hrv.get("status") or "") or None,
        "body_battery_start": start,
        "body_battery_end": end,
        "body_battery_charged": charged,
        "breathing_rate": pick_first_numeric(sleep, [("dailySleepDTO", "avgSleepRespirationValue"),
                                                      ("avgSleepRespirationValue",)]) or pick_first_numeric(
                                                          stats, [("avgRespirationValue",), ("averageRespiration",)]),
    }


def extract_vo2max_value(max_metrics_data: Any) -> float | None:
    if isinstance(max_metrics_data, list):
        for entry in max_metrics_data:
            value = coerce_numeric(entry.get("generic")) if isinstance(entry, dict) else None
            if value is not None:
                return value
    direct = pick_first_numeric(
        max_metrics_data,
        [("generic",), ("vo2MaxPreciseValue",), ("value",)],
    )
    if direct is not None:
        return direct
    values = flatten_candidate_values(
        max_metrics_data,
        {"generic", "vo2MaxPreciseValue", "vO2MaxValue", "value"},
    )
    return values[0] if values else None


def normalize_recovery_time_to_hours(value: float | None) -> float | None:
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


def normalize_recovery_time_hours(*payloads: Any) -> float | None:
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
        direct = pick_first_numeric(payload, candidates)
        normalized = normalize_recovery_time_to_hours(direct)
        if normalized is not None:
            return normalized

        flattened = flatten_candidate_values(
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
            normalized = normalize_recovery_time_to_hours(value)
            if normalized is not None:
                return normalized
    return None


def normalize_csv_activity_row(row: Any, *, user_id: int, index: int, parsed_date: Any) -> dict[str, Any] | None:
    if pd.isna(parsed_date):
        return None
    external_id = row.get("external_id", row.get("activityId", index + 1))
    row_distance = normalize_distance(coerce_numeric(row.get("distance")))
    row_duration = normalize_duration(coerce_numeric(row.get("duration")))
    row_pace = coerce_numeric(row.get("pace"))
    if row_pace is None and row_distance > 0:
        row_pace = row_duration / row_distance

    return {
        "user_id": user_id,
        "external_id": str(external_id),
        "activity_name": clean_text(row.get("activity_name", row.get("activityName", row.get("name", row.get("title"))))),
        "date": parsed_date.date(),
        "type": parse_activity_type(row.get("type", row.get("activityType", row.get("activity_type")))),
        "distance": round(row_distance, 2),
        "duration": round(row_duration, 2),
        "pace": round(row_pace, 2) if row_pace is not None else None,
        "avg_hr": coerce_numeric(row.get("avg_hr", row.get("averageHR"))),
        "max_hr": coerce_numeric(row.get("max_hr", row.get("maxHR"))),
        "cadence": coerce_numeric(row.get("cadence", row.get("averageRunningCadenceInStepsPerMinute"))),
        "elevation": coerce_numeric(row.get("elevation", row.get("elevationGain"))),
        "training_effect": coerce_numeric(row.get("training_effect", row.get("activityTrainingLoad"))),
        "aerobic_effect": coerce_numeric(row.get("aerobic_effect", row.get("aerobicTrainingEffect"))),
        "anaerobic_effect": coerce_numeric(row.get("anaerobic_effect", row.get("anaerobicTrainingEffect"))),
        "notes": row.get("notes"),
    }


def normalize_csv_health_row(row: Any, *, user_id: int, parsed_date: Any) -> dict[str, Any] | None:
    if pd.isna(parsed_date):
        return None
    return {
        "user_id": user_id,
        "date": parsed_date.date(),
        "sleep_duration": coerce_numeric(row.get("sleep_duration", row.get("sleepDurationHours"))),
        "sleep_score": coerce_numeric(row.get("sleep_score")),
        "resting_hr": coerce_numeric(row.get("resting_hr", row.get("restingHeartRate"))),
        "hrv": coerce_numeric(row.get("hrv")),
        "stress": coerce_numeric(row.get("stress")),
        "body_battery": coerce_numeric(row.get("body_battery", row.get("bodyBattery"))),
        "recovery_time": coerce_numeric(row.get("recovery_time", row.get("recoveryTime"))),
        "vo2max": coerce_numeric(row.get("vo2max", row.get("vO2MaxValue"))),
    }


def normalize_live_activity_row(row: dict[str, Any], *, user_id: int) -> dict[str, Any] | None:
    row_distance = normalize_distance(coerce_numeric(row.get("distance")))
    row_duration = normalize_duration(coerce_numeric(row.get("duration")))
    row_pace = row_duration / row_distance if row_distance > 0 else None
    activity_date = safe_date(row.get("startTimeLocal") or row.get("startTimeGMT"))
    if activity_date is None:
        return None

    return {
        "user_id": user_id,
        "external_id": str(row.get("activityId") or ""),
        "activity_name": clean_text(row.get("activityName") or row.get("activityNameOriginal")),
        "date": activity_date,
        "type": parse_activity_type(row.get("activityType")),
        "distance": round(row_distance, 2),
        "duration": round(row_duration, 2),
        "pace": round(row_pace, 2) if row_pace is not None else None,
        "avg_hr": coerce_numeric(row.get("averageHR")),
        "max_hr": coerce_numeric(row.get("maxHR")),
        "cadence": coerce_numeric(row.get("averageRunningCadenceInStepsPerMinute")),
        "elevation": coerce_numeric(row.get("elevationGain")),
        "training_effect": coerce_numeric(row.get("activityTrainingLoad")),
        "aerobic_effect": coerce_numeric(row.get("aerobicTrainingEffect")),
        "anaerobic_effect": coerce_numeric(row.get("anaerobicTrainingEffect")),
        "notes": None,
    }


_HEALTH_FIELD_SOURCES = {
    "sleep_duration": ("sleep",),
    "sleep_score": ("sleep",),
    "sleep_deep_min": ("sleep",),
    "sleep_rem_min": ("sleep",),
    "sleep_light_min": ("sleep",),
    "sleep_awake_min": ("sleep",),
    "sleep_bedtime": ("sleep",),
    "sleep_wake_time": ("sleep",),
    "sleep_wakeups": ("sleep",),
    "resting_hr": ("stats",),
    "stress": ("stats",),
    "hrv": ("hrv",),
    "hrv_weekly_avg": ("hrv",),
    "hrv_baseline_low": ("hrv",),
    "hrv_baseline_high": ("hrv",),
    "hrv_status": ("hrv",),
    "body_battery": ("body_battery",),
    "body_battery_start": ("body_battery",),
    "body_battery_end": ("body_battery",),
    "body_battery_charged": ("body_battery",),
    "vo2max": ("max_metrics",),
    "recovery_time": ("training_readiness", "training_status", "stats"),
    "breathing_rate": ("sleep", "stats"),
}


def normalize_live_health_row(
    *,
    user_id: int,
    current_day: date,
    stats: dict[str, Any],
    sleep: dict[str, Any],
    body_battery: Any,
    hrv: Any,
    max_metrics: Any,
    training_readiness: Any,
    training_status: Any,
    timezone: str = "UTC",
    failed_sources: frozenset[str] = frozenset(),
    include_empty: bool = False,
) -> dict[str, Any] | None:
    resting_hr = pick_first_numeric(
        stats,
        [
            ("restingHeartRate",),
            ("restingHR",),
            ("allMetrics", "metricsMap", "WELLNESS_RESTING_HEART_RATE", "value"),
        ],
    )
    stress = pick_first_numeric(
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
        "sleep_duration": extract_sleep_duration_hours(sleep),
        "sleep_score": extract_sleep_score(sleep),
        "resting_hr": resting_hr,
        "hrv": extract_hrv_value(hrv),
        "stress": stress,
        "body_battery": extract_body_battery_value(body_battery),
        "recovery_time": normalize_recovery_time_hours(training_readiness, training_status, stats),
        "vo2max": extract_vo2max_value(max_metrics),
        **extract_night_details(sleep, hrv if isinstance(hrv, dict) else {}, stats, body_battery, timezone),
    }
    for field, sources in _HEALTH_FIELD_SOURCES.items():
        if row[field] is None and any(source in failed_sources for source in sources):
            del row[field]
    if any(value is not None for key, value in row.items() if key not in {"user_id", "date"}):
        return row
    return row if include_empty else None


_extract_recovery_time_hours = normalize_recovery_time_hours
