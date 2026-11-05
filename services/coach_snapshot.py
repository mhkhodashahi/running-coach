"""Bounded, provenance-preserving serialization of daily metrics for coach inputs."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any


def activity_opinion_snapshot(snapshot: Any, activity_id: int) -> dict[str, Any]:
    """Serialize the daily snapshot and matching activity metrics for an opinion."""
    session = next((item for item in snapshot.sessions if item.activity_id == activity_id), None)
    activity_session = None
    if session is not None:
        activity_session = {
            "activity_id": session.activity_id,
            "sport": session.sport,
            "load": asdict(session.load),
            "hrmax": asdict(session.hrmax),
            "hr_zones": [{"zone": zone.name, "seconds": zone.seconds.value,
                          "percent": zone.percent.value} for zone in session.zones],
            "hr_zone_source": "metrics.session_metrics / activity_track_points.heart_rate",
            "observed_seconds": session.observed_seconds.value,
        }
    return {
        "as_of": snapshot.as_of,
        "timezone": snapshot.timezone,
        "baselines": [asdict(item) for item in snapshot.baselines],
        "current_health": {name: asdict(value) for name, value in snapshot.current_health},
        "readiness": asdict(snapshot.readiness),
        "load": asdict(snapshot.load),
        "activity_session": activity_session,
        "daily_sport_loads": [{"sport": item.sport, "load_trimp": item.load.value,
                               "source": "metrics.daily_sport_loads"} for item in snapshot.sport_loads
                              if item.period == "daily" and item.load.provenance.window_end == snapshot.as_of],
    }
