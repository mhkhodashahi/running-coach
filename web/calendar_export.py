"""Calendar export for athlete-approved planned sessions."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any


def _escape(value: str) -> str:
    return (value.replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n")
            .replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;"))


def _fold(line: str) -> str:
    """Fold at 75 UTF-8 octets without splitting a Unicode character."""
    parts: list[str] = []
    current = ""
    width = 0
    for character in line:
        size = len(character.encode("utf-8"))
        if width + size > 75:
            parts.append(current)
            current = " "
            width = 1
        current += character
        width += size
    parts.append(current)
    return "\r\n".join(parts)


def _workout_description(session: dict[str, Any]) -> str:
    workout = session.get("workout_json")
    if isinstance(workout, str):
        import json

        try:
            workout = json.loads(workout)
        except json.JSONDecodeError:
            workout = None
    if not isinstance(workout, dict):
        workout = {}

    lines = [f"{session['sport'].title()} · {session['intent'].replace('_', ' ').title()}",
             f"Duration: {session['duration_min']} min"]
    if session.get("hr_cap_bpm") is not None:
        lines.append(f"Heart-rate cap: {session['hr_cap_bpm']} bpm")
    for field, label in (("purpose", "Purpose"), ("why_session", "Why this session"),
                         ("why_day", "Why this day"), ("how_it_feels", "How it should feel"),
                         ("done_right_if", "Done right if"), ("fallback", "If tired")):
        value = workout.get(field)
        if value:
            lines.append(f"{label}: {value}")
    for step in workout.get("steps", []):
        if not isinstance(step, dict):
            continue
        detail = step.get("label", "Step")
        if step.get("reps", 1) > 1:
            detail += f" · {step['reps']} repetitions"
        if step.get("duration_min") is not None:
            detail += f" · {step['duration_min']} min"
        for key in ("hr_target", "pace_target", "effort"):
            if step.get(key):
                detail += f" · {step[key]}"
        if step.get("exercises"):
            detail += " · " + ", ".join(str(item) for item in step["exercises"])
        lines.append(detail)
    return "\n".join(lines)


def session_ical(session: dict[str, Any], *, generated_at: datetime | None = None) -> str:
    """Create an all-day RFC 5545 event; sessions currently have no start time."""
    session_date = date.fromisoformat(str(session["date"]))
    end_date = session_date.fromordinal(session_date.toordinal() + 1)
    stamp = generated_at or datetime.now(UTC)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    stamp = stamp.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    workout = session.get("workout_json")
    if isinstance(workout, str):
        import json

        try:
            workout = json.loads(workout)
        except json.JSONDecodeError:
            workout = None
    title = workout.get("title") if isinstance(workout, dict) else None
    title = title or f"{session['sport'].title()} · {session['intent'].replace('_', ' ').title()}"
    uid = f"pulse-session-{session['id']}@pulse-coach.local"
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Pulse Coach//Training Session//EN",
        "CALSCALE:GREGORIAN", "BEGIN:VEVENT", f"UID:{_escape(uid)}", f"DTSTAMP:{stamp}",
        f"DTSTART;VALUE=DATE:{session_date:%Y%m%d}", f"DTEND;VALUE=DATE:{end_date:%Y%m%d}",
        f"SUMMARY:{_escape(str(title))}", f"DESCRIPTION:{_escape(_workout_description(session))}",
        "END:VEVENT", "END:VCALENDAR",
    ]
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
