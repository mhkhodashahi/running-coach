"""Performance Dashboard page."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from streamlit.components.v1 import html

from config import BASE_DIR
from utils.bootstrap import load_training_bundle

st.set_page_config(page_title="Performance Dashboard", page_icon="P", layout="wide")


def _clean_number(value: Any) -> float | None:
    """Return JSON-safe numeric values."""

    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _sport_label(activity_type: str | None) -> str:
    raw = str(activity_type or "").lower()
    if any(term in raw for term in ("run", "trail", "treadmill")):
        return "Running"
    if any(term in raw for term in ("cycl", "bike", "biking")):
        return "Cycling"
    if "swim" in raw:
        return "Swimming"
    if any(term in raw for term in ("strength", "weight", "gym")):
        return "Strength"
    if any(term in raw for term in ("walk", "hike")):
        return "Walking"
    return "Running"


def _subtype_label(activity_type: str | None) -> str:
    raw = str(activity_type or "").lower()
    if "trail" in raw:
        return "Trail"
    if "treadmill" in raw or "indoor_running" in raw:
        return "Treadmill"
    if "indoor" in raw and any(term in raw for term in ("bike", "cycl")):
        return "Indoor Bike"
    if any(term in raw for term in ("bike", "cycl")):
        return "Outdoor Bike"
    if "open" in raw and "water" in raw:
        return "Open Water"
    if "swim" in raw:
        return "Pool"
    return "Road"


def _workout_type(row: pd.Series) -> str:
    text = f"{row.get('activity_name', '')} {row.get('type', '')} {row.get('notes', '')}".lower()
    distance = _clean_number(row.get("distance")) or 0
    pace = _clean_number(row.get("pace"))
    aerobic = _clean_number(row.get("aerobic_effect")) or 0
    anaerobic = _clean_number(row.get("anaerobic_effect")) or 0
    if "race" in text:
        return "Race"
    if any(term in text for term in ("interval", "repeat", "speed")) or anaerobic >= 1.4:
        return "Interval"
    if any(term in text for term in ("tempo", "threshold")) or aerobic >= 3.8:
        return "Tempo"
    if distance >= 15:
        return "Long"
    if pace and pace > 6.1:
        return "Recovery"
    return "Easy"


def _tags_for(row: pd.Series) -> list[str]:
    text = f"{row.get('activity_name', '')} {row.get('type', '')} {row.get('notes', '')}".lower()
    tags: list[str] = []
    if any(term in text for term in ("race", "simulation")):
        tags.append("Race Block")
    if any(term in text for term in ("travel", "hotel")):
        tags.append("Travel")
    if any(term in text for term in ("ill", "sick", "cold")):
        tags.append("Illness")
    if any(term in text for term in ("taper", "easy week")):
        tags.append("Taper")
    tags.append("Build" if (_clean_number(row.get("distance")) or 0) >= 12 else "Base")
    return list(dict.fromkeys(tags))


def _build_derived(activities: pd.DataFrame, health: pd.DataFrame) -> list[dict[str, Any]]:
    if activities.empty and health.empty:
        return []

    dates = []
    if not activities.empty:
        dates.extend(pd.to_datetime(activities["date"]).dt.normalize().tolist())
    if not health.empty:
        dates.extend(pd.to_datetime(health["date"]).dt.normalize().tolist())
    start = min(dates)
    end = max(dates)
    all_days = pd.date_range(start, end, freq="D")
    runs = activities.copy()
    if not runs.empty:
        runs["date"] = pd.to_datetime(runs["date"]).dt.normalize()
        runs = runs[runs["type"].fillna("").str.contains("run|trail|treadmill", case=False, na=False)]
    h = health.copy()
    if not h.empty:
        h["date"] = pd.to_datetime(h["date"]).dt.normalize()
        h = h.set_index("date")

    rows = []
    for day in all_days:
        recent = runs[(runs["date"] >= day - timedelta(days=27)) & (runs["date"] <= day)] if not runs.empty else pd.DataFrame()
        recent_distance = float(recent["distance"].sum()) if not recent.empty else 0.0
        recent_duration = float(recent["duration"].sum()) if not recent.empty else 0.0
        recent_elevation = float(recent["elevation"].fillna(0).sum()) if not recent.empty else 0.0
        day_health = h.loc[day] if day in h.index else None
        sleep = _clean_number(day_health.get("sleep_score")) if day_health is not None else 72
        battery = _clean_number(day_health.get("body_battery")) if day_health is not None else 60
        stress = _clean_number(day_health.get("stress")) if day_health is not None else 35
        readiness = max(0, min(100, (sleep or 72) * 0.42 + (battery or 60) * 0.38 + (100 - (stress or 35)) * 0.20))
        endurance = max(25, min(100, 42 + recent_distance * 0.55 + recent_duration * 0.02))
        hill = max(20, min(100, 38 + recent_elevation / 55))
        race5k = max(17.0, 29.5 - endurance * 0.075)
        rows.append(
            {
                "date": day.date().isoformat(),
                "enduranceScore": round(endurance, 1),
                "hillScore": round(hill, 1),
                "racePredictor5k": round(race5k, 2),
                "readinessScore": round(readiness, 1),
            }
        )
    return rows


def _dashboard_payload() -> dict[str, Any]:
    bundle = load_training_bundle()
    activities = bundle.activities.copy()
    health = bundle.health_metrics.copy()

    activity_rows: list[dict[str, Any]] = []
    if not activities.empty:
        activities["date"] = pd.to_datetime(activities["date"])
        for _, row in activities.iterrows():
            sport = _sport_label(row.get("type"))
            subtype = _subtype_label(row.get("type"))
            environment = "Indoor" if subtype in {"Treadmill", "Indoor Bike", "Pool"} else "Outdoor"
            activity_rows.append(
                {
                    "date": row["date"].date().isoformat(),
                    "sport": sport,
                    "subtype": subtype,
                    "durationMin": round(_clean_number(row.get("duration")) or 0, 1),
                    "distanceKm": round(_clean_number(row.get("distance")) or 0, 2),
                    "elevationM": round(_clean_number(row.get("elevation")) or 0, 0),
                    "avgHR": _clean_number(row.get("avg_hr")),
                    "avgPace": _clean_number(row.get("pace")),
                    "avgPower": None,
                    "load": round(
                        (_clean_number(row.get("distance")) or 0) * 3
                        + (_clean_number(row.get("duration")) or 0) * 0.3
                        + (_clean_number(row.get("aerobic_effect")) or 0) * 12
                        + (_clean_number(row.get("anaerobic_effect")) or 0) * 16,
                        0,
                    ),
                    "workoutType": _workout_type(row),
                    "environment": environment,
                    "device": "Watch",
                    "tags": _tags_for(row),
                }
            )

    health_rows: list[dict[str, Any]] = []
    if not health.empty:
        health["date"] = pd.to_datetime(health["date"])
        for _, row in health.iterrows():
            hrv = _clean_number(row.get("hrv"))
            health_rows.append(
                {
                    "date": row["date"].date().isoformat(),
                    "sleepScore": _clean_number(row.get("sleep_score")),
                    "bodyBattery": _clean_number(row.get("body_battery")),
                    "restingHR": _clean_number(row.get("resting_hr")),
                    "stress": _clean_number(row.get("stress")),
                    "hrvStatus": "Balanced" if hrv and hrv >= 55 else "Low" if hrv and hrv < 40 else "Unbalanced",
                }
            )

    return {
        "source": "real",
        "activities": activity_rows,
        "health": health_rows,
        "derived": _build_derived(activities, health),
    }


dashboard_path = Path(BASE_DIR) / "app" / "performance_dashboard.html"
dashboard_html = dashboard_path.read_text(encoding="utf-8")
payload_json = json.dumps(_dashboard_payload(), allow_nan=False)
dashboard_html = dashboard_html.replace(
    "</head>",
    f"<script>window.PERFORMANCE_DASHBOARD_DATA = {payload_json};</script></head>",
)
html(dashboard_html, height=1200, scrolling=True)
