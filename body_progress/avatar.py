"""Reusable avatar-state logic for training dashboards."""

from __future__ import annotations

from datetime import date
from typing import Any

from body_progress.domain import AvatarState, BodyScanSummary


def build_avatar_state(snapshot: dict[str, Any], scans: list[BodyScanSummary]) -> AvatarState:
    """Translate training and scan context into a simple avatar state."""

    readiness = snapshot.get("readiness", {})
    fatigue = snapshot.get("fatigue", {})
    weekly = snapshot.get("weekly_mileage", {})
    recovery = snapshot.get("recovery", {})

    readiness_score = float(readiness.get("score") or 0)
    fatigue_level = str(fatigue.get("level") or "unknown")
    weekly_km = float(weekly.get("7d") or 0)
    sleep_score = recovery.get("sleep_score")
    body_battery = recovery.get("body_battery")
    latest_scan_date: date | None = max((scan.scan_date for scan in scans), default=None)

    if readiness_score >= 75 and fatigue_level != "high":
        title = "Ready Runner"
        color = "#16a34a"
        subtitle = "Body and training signals are supportive."
    elif fatigue_level == "high" or readiness_score < 55:
        title = "Recovery Mode"
        color = "#f59e0b"
        subtitle = "The avatar is holding back until recovery improves."
    else:
        title = "Building Form"
        color = "#fc4c02"
        subtitle = "Training is moving, but recovery still matters."

    recovery_bits = []
    if sleep_score is not None:
        recovery_bits.append(f"sleep {float(sleep_score):.0f}")
    if body_battery is not None:
        recovery_bits.append(f"body battery {float(body_battery):.0f}")

    return AvatarState(
        title=title,
        subtitle=subtitle,
        readiness_label=f"Readiness {readiness_score:.0f}",
        load_label=f"7-day load {weekly_km:.1f} km",
        recovery_label=", ".join(recovery_bits) if recovery_bits else "Recovery data unavailable",
        color=color,
        body_scan_count=len(scans),
        latest_scan_date=latest_scan_date,
    )
