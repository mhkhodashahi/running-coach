"""Pure presentation helpers for the Today morning and last-session cards."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from metrics.sports import RECOMMENDABLE_SPORTS, sport_category
from web.formatting import activity_duration, short_date


def brief_card(brief: Any | None, sync: str) -> dict[str, Any]:
    if brief is None:
        return {"ready": False, "message": f"Your morning brief arrives after the morning sync · {sync}"}
    sections = brief.sections
    return {"ready": True, "source": brief.source,
            "visible": tuple((label, sections[key]) for key, label in
                             (("sleep", "Sleep"), ("hrv", "HRV")) if sections.get(key)),
            "more": tuple((label, sections[key]) for key, label in
                          (("heart", "Heart and energy"), ("yesterday", "Yesterday"), ("tip", "Tip"))
                          if sections.get(key))}


def last_session(rows: list[dict[str, Any]], now: datetime) -> dict[str, Any] | None:
    """Select the newest eligible session with a reliable start in the last 48 hours."""
    eligible = []
    for row in rows:
        day = date.fromisoformat(row["date"][:10])
        sport = sport_category(row["type"], day)
        if sport not in RECOMMENDABLE_SPORTS:
            continue
        raw = row.get("started_at")
        if raw:
            started = datetime.fromisoformat(raw)
            if started.tzinfo is None:
                started = started.replace(tzinfo=now.tzinfo)
        else:
            started = datetime.combine(day, datetime.min.time(), tzinfo=now.tzinfo)
        if timedelta(0) <= now - started <= timedelta(hours=48):
            eligible.append((started, row["id"], row, sport))
    if not eligible:
        return None
    _, _, row, sport = max(eligible, key=lambda item: (item[0], item[1]))
    opinion = row.get("opinion")
    icons = {"good": "check", "watch": "minus", "poor": "close"}
    return {"id": row["id"], "sport": sport, "date": short_date(row["date"]),
            "duration": activity_duration(row.get("duration")),
            "load": f"{round(row['load'])} load" if row.get("load") is not None else None,
            "review_supported": sport == "running", "headline": opinion.headline if opinion else None,
            "verdicts": tuple({"word": item.word, "aspect": item.aspect,
                               "icon": icons[item.rating]} for item in opinion.verdicts[:4]) if opinion else ()}
