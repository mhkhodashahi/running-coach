"""Activity views and explicit actions for the server-rendered web UI."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from coach.agent import CoachAgent, _user_lock
from coach.planning import propose_opinion_recommendations
from coach.tools import CoachTools
from config import Settings
from db.models import User
from llm.factory import get_llm_client
from metrics import get_daily_snapshot
from metrics.sports import RECOMMENDABLE_SPORTS, sport_category
from services.activity_coaching_service import ActivityCoachingService
from services.coach_facts import effort_vs_hr
from services.coach_opinion import load_opinion
from services.effort_service import rate_activity
from services.fact_display import duration as lap_duration
from services.fact_display import pace as format_pace
from services.training_chat_service import TrainingChatService
from web.charts import heart_rate_chart
from web.formatting import activity_distance, activity_duration, metric, short_date
from web.today import sync_label

PAGE_SIZE = 20
INTENTS = ("recovery", "easy", "steady", "tempo", "race")
RUN_SUGGESTIONS = ("Why was my HR higher than usual?", "Compare with my best 5 km",
                   "What should my next run be?")
OTHER_SUGGESTIONS = ("Was this harder than it looked on HR?",
                     "How should I recover before my next session?", "Compare with my last session")


def _db(database: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _local_day(settings: Settings) -> date:
    return datetime.now(ZoneInfo(settings.local_timezone)).date()


def _tools(settings: Settings) -> CoachTools:
    return CoachTools(settings.db_path, settings.default_user_id, settings.local_timezone,
                      settings.sleep_goal_hours)


def _session_snapshot(settings: Settings, day: date, activity_id: int):
    snapshot = get_daily_snapshot(day, database=settings.db_path, user_id=settings.default_user_id,
                                  timezone=settings.local_timezone, sleep_goal_hours=settings.sleep_goal_hours)
    return next((item for item in snapshot.sessions if item.activity_id == activity_id), None)


def _zones(item: Any) -> list[dict[str, Any]]:
    if item is None:
        return []
    return [{"name": zone.name, "percent": zone.percent.value,
             "css_class": f"zone-{zone.name[1]}" if zone.name.startswith("Z") else "zone-below",
             "minutes": round(zone.seconds.value / 60, 1) if zone.seconds.value is not None else None}
            for zone in item.zones]


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _sport(row: sqlite3.Row) -> str:
    return sport_category(row["type"], date.fromisoformat(row["date"]))


def _display_sport(row: sqlite3.Row) -> str:
    category = _sport(row)
    return category.title() if category != "other" else row["type"].replace("_", " ").title()


def list_context(settings: Settings, *, sport: str | None = None, start: date | None = None,
                 end: date | None = None, show_walks: bool = False, page: int = 1) -> dict[str, Any]:
    """Build one 20-row slice, with complete-week headers and bounded per-row details."""
    if sport not in (None, *RECOMMENDABLE_SPORTS, "walking", "other"):
        raise ValueError("Unknown sport filter")
    if page < 1 or page > 10000 or (start and end and start > end):
        raise ValueError("Invalid activity range or page")
    with _db(settings.db_path) as connection:
        rows = connection.execute(
            "SELECT a.*,e.rpe, i.id AS opinion_id FROM activities a "
            "LEFT JOIN activity_efforts e ON e.activity_id=a.id "
            "LEFT JOIN activity_coaching_insights i ON i.activity_id=a.id AND i.user_id=a.user_id "
            "WHERE a.user_id=? AND (? IS NULL OR a.date>=?) AND (? IS NULL OR a.date<=?) "
            "ORDER BY a.date DESC,a.id DESC",
            (settings.default_user_id, start.isoformat() if start else None, start.isoformat() if start else None,
             end.isoformat() if end else None, end.isoformat() if end else None)).fetchall()
    def visible(row: sqlite3.Row) -> bool:
        category = _sport(row)
        walking = row["type"].strip().lower() == "walking"
        if category in ("excluded", "mobility") or (walking and not show_walks and sport != "walking"):
            return False
        return sport is None or (sport == "walking" and walking) or (sport == category and not walking)

    filtered = [row for row in rows if visible(row)]
    chosen = filtered[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    weeks: dict[date, list[dict[str, Any]]] = defaultdict(list)
    snapshot_cache: dict[date, dict[int, Any]] = {}

    def session_for(row: sqlite3.Row) -> Any:
        day = date.fromisoformat(row["date"])
        if day not in snapshot_cache:
            snapshot = get_daily_snapshot(day, database=settings.db_path, user_id=settings.default_user_id,
                                          timezone=settings.local_timezone,
                                          sleep_goal_hours=settings.sleep_goal_hours)
            snapshot_cache[day] = {item.activity_id: item for item in snapshot.sessions}
        return snapshot_cache[day].get(row["id"])

    for row in chosen:
        day = date.fromisoformat(row["date"])
        category = _sport(row)
        session = session_for(row)
        zone_items = _zones(session)
        weeks[_week_start(day)].append({
            "id": row["id"], "date": short_date(day), "sport": _display_sport(row),
            "distance": activity_distance(row["distance"]) if category == "running" or
            row["type"].strip().lower() == "walking" else "—",
            "duration": activity_duration(row["duration"]), "zones": zone_items,
            "zone_pairs": [(zone["name"], zone["percent"] or 0) for zone in zone_items],
            "rpe": row["rpe"], "opinion": row["opinion_id"] is not None,
        })
    all_weeks: dict[date, list[sqlite3.Row]] = defaultdict(list)
    for row in filtered:
        all_weeks[_week_start(date.fromisoformat(row["date"]))].append(row)
    groups = []
    for monday, items in weeks.items():
        whole = all_weeks[monday]
        loads = [session_for(row) for row in whole]
        values = [item.load.value for item in loads if item is not None and item.load.value is not None]
        total = sum(values) if loads and len(values) == len(loads) else None
        sports = list(dict.fromkeys(_display_sport(row) for row in whole))
        groups.append({"label": f"{short_date(monday)} – {short_date(monday + timedelta(days=6))}",
                       "load": f"{total:.0f}" if total is not None else None,
                       "sessions": len(whole),
                       "sports": sports, "items": items})
    filter_query = urlencode({"sport": sport or "", "start": start.isoformat() if start else "",
                              "end": end.isoformat() if end else "", "show_walks": str(show_walks).lower()})
    return {"groups": groups, "page": page, "has_more": len(filtered) > page * PAGE_SIZE,
            "filter_query": filter_query,
            "sport_filter": sport or "", "start": start.isoformat() if start else "",
            "end": end.isoformat() if end else "", "show_walks": show_walks,
            "sync": sync_label(settings, _local_day(settings))}


def _first_time(connection: sqlite3.Connection, activity_id: int, day: date) -> str | None:
    row = connection.execute("SELECT MIN(start_time) FROM activity_laps WHERE activity_id=?", (activity_id,)).fetchone()
    raw = row[0] if row else None
    if raw is None:
        row = connection.execute("SELECT MIN(timestamp) FROM activity_track_points WHERE activity_id=?",
                                 (activity_id,)).fetchone()
        raw = row[0] if row else None
    if raw is None:
        return None
    stamp = datetime.fromisoformat(raw)
    return stamp.strftime("%H:%M") if stamp.date() == day else None


def _stats(row: sqlite3.Row, session: Any,
           cadence: tuple[float | None, float | None],
           effort_label: str | None = None) -> list[tuple[str, str | None]]:
    sport = _sport(row)
    values: list[tuple[str, str | None]] = []
    walking = row["type"].strip().lower() == "walking"
    if sport == "running" or walking:
        values.extend((("Distance", activity_distance(row["distance"])),
                       ("Time", activity_duration(row["duration"])),
                       ("Avg pace", format_pace(row["pace"])),
                       ("Avg HR", metric(row["avg_hr"], "bpm")),
                       ("Max HR", metric(row["max_hr"], "bpm"))))
        if sport == "running":
            values.extend((("Cadence", f"{round(cadence[0])}–{round(cadence[1])} spm"
                            if cadence[0] and cadence[1] else None),
                           ("Elevation", metric(row["elevation"], "m"))))
            if row["rpe"] is not None:
                values.append(("Effort", f"{row['rpe']}/10"))
                if effort_label:
                    values.append(("Effort vs HR", effort_label))
    else:
        values.extend((("Duration", activity_duration(row["duration"])),
                       ("Avg HR", metric(row["avg_hr"], "bpm")),
                       ("Max HR", metric(row["max_hr"], "bpm")),
                       ("Session load", metric(session.load.value, "TRIMP") if session else None),
                       ("Effort", f"{row['rpe']}/10" if row["rpe"] is not None else None)))
        if effort_label:
            values.append(("Effort vs HR", effort_label))
    if not walking:
        values.extend((("Aerobic TE", metric(row["aerobic_effect"], precision=1)),
                       ("Anaerobic TE", metric(row["anaerobic_effect"], precision=1))))
    return values


def _similar(settings: Settings, activity_id: int) -> list[dict[str, Any]]:
    try:
        result = _tools(settings).compare_sessions(activity_id)
    except ValueError:
        return []
    items = []
    with _db(settings.db_path) as connection:
        durations = {row["id"]: row["duration"] for row in connection.execute(
            "SELECT id,duration FROM activities WHERE user_id=? AND id IN (" +
            ",".join("?" for _ in result["sessions"]) + ")",
            (settings.default_user_id, *(item["activity_id"] for item in result["sessions"]))).fetchall()} if result["sessions"] else {}
    for row in result["sessions"][:5]:
        facts = {fact["id"].removeprefix(f"ACT_{row['activity_id']}_"): fact["display"]
                 for fact in row["facts"]}
        by_id = {fact["id"]: fact["display"] for fact in row["facts"]}
        identifier = row["activity_id"]
        efficiency = by_id.get(f"COMPARE_{identifier}_EFFICIENCY_LABEL", "similar")
        difference = by_id.get(f"COMPARE_{identifier}_DURATION_DELTA" if result["sport"] in
                               ("volleyball", "football", "gym") else f"COMPARE_{identifier}_PACE_DELTA")
        hr_difference = by_id.get(f"COMPARE_{identifier}_HR_DELTA")
        differences = " · ".join(part.replace("-", "−") for part in (difference, hr_difference) if part)
        items.append({"id": row["activity_id"], "date": short_date(row["date"]),
                      "pace": facts.get("AVG_PACE") if result["sport"] == "running" else None,
                      "duration": activity_duration(durations.get(row["activity_id"])),
                      "hr": facts.get("AVG_HR"), "readiness": facts.get("READINESS")
                      if facts.get("READINESS") != "No data" else None,
                      "difference": differences or None, "efficiency": efficiency})
    return items


def detail_context(settings: Settings, activity_id: int) -> dict[str, Any]:
    with _db(settings.db_path) as connection:
        row = connection.execute("SELECT a.*,e.rpe FROM activities a LEFT JOIN activity_efforts e "
                                 "ON e.activity_id=a.id WHERE a.id=? AND a.user_id=?",
                                 (activity_id, settings.default_user_id)).fetchone()
        if row is None:
            raise ValueError("Activity not found")
        day = date.fromisoformat(row["date"])
        laps = [dict(item) for item in connection.execute(
            "SELECT lap_index,lap_type,distance,duration,pace,avg_hr,avg_cadence FROM activity_laps "
            "WHERE activity_id=? ORDER BY lap_index", (activity_id,))]
        points = [dict(item) for item in connection.execute(
            "SELECT elapsed_seconds,heart_rate FROM activity_track_points WHERE activity_id=? "
            "AND heart_rate IS NOT NULL ORDER BY point_index", (activity_id,))]
        cadence = connection.execute("SELECT MIN(avg_cadence),MAX(avg_cadence) FROM activity_laps "
                                     "WHERE activity_id=? AND distance>=0.9", (activity_id,)).fetchone()
        user = connection.execute("SELECT max_hr,age FROM users WHERE id=?", (settings.default_user_id,)).fetchone()
        opinion_row = connection.execute("SELECT * FROM activity_coaching_insights WHERE activity_id=? AND user_id=?",
                                         (activity_id, settings.default_user_id)).fetchone()
        prev_row = connection.execute("SELECT id FROM activities WHERE user_id=? AND "
                                      "(date<? OR (date=? AND id<?)) ORDER BY date DESC,id DESC LIMIT 1",
                                      (settings.default_user_id, row["date"], row["date"], activity_id)).fetchone()
        next_row = connection.execute("SELECT id FROM activities WHERE user_id=? AND "
                                      "(date>? OR (date=? AND id>?)) ORDER BY date,id LIMIT 1",
                                      (settings.default_user_id, row["date"], row["date"], activity_id)).fetchone()
        clock = _first_time(connection, activity_id, day)
    session = _session_snapshot(settings, day, activity_id)
    opinion = load_opinion(dict(opinion_row)).model_dump() if opinion_row else None
    zones = _zones(session)
    low_zone_share = (sum(zone["percent"] or 0 for zone in zones if zone["name"].startswith(("Z1", "Z2")))
                      if zones else None)
    effort_label = effort_vs_hr(row["rpe"], low_zone_share)
    max_hr = user[0] or (220 - user[1] if user and user[1] else None) if user else None
    bounds = (settings.hr_zones or tuple((f"Z{index}", round(low * max_hr), round(high * max_hr))
                                      for index, (low, high) in enumerate(
                                          ((.5, .6), (.6, .7), (.7, .8), (.8, .9), (.9, 1)), 1))
              if max_hr else ())
    accounted_km = 0.0
    for lap in laps:
        raw_distance = lap["distance"]
        remaining = max(0.0, row["distance"] - accounted_km)
        # Old Garmin partial laps can retain metres when full laps were normalized to km.
        metres_partial = (raw_distance is not None and raw_distance > remaining + 0.1
                          and raw_distance <= 100 and lap["duration"] is not None
                          and lap["duration"] < 1)
        lap_km = raw_distance / 1000 if metres_partial else raw_distance
        lap["distance_km"] = lap_km
        if lap_km is not None:
            accounted_km += lap_km
        lap["distance_label"] = (f"{raw_distance:.2f} m" if metres_partial else
                                 f"{lap_km:.2f} km" if lap_km is not None else None)
        lap["partial"] = lap_km is not None and lap_km < 0.9
        lap["pace_label"] = format_pace(lap["pace"]) if _sport(row) == "running" and not lap["partial"] else None
        lap["duration_label"] = lap_duration(lap["duration"])
        lap["zone"] = next((name.split()[0] for name, low, high in bounds if not lap["partial"]
                            and lap["avg_hr"] is not None
                            and low <= lap["avg_hr"] < (high if high is not None else float("inf"))), None)
    hr_chart = heart_rate_chart(points, settings.hr_zones, max_hr, row["duration"])
    only_lap = laps[0] if len(laps) == 1 else None
    whole_lap = (only_lap is not None and (
        only_lap["distance_km"] is not None and
        abs(only_lap["distance_km"] - row["distance"]) <= max(.02, row["distance"] * .02)
        or only_lap["distance_km"] is None and only_lap["duration"] is not None
        and abs(only_lap["duration"] - row["duration"]) <= 1))
    return {"activity": {"id": activity_id, "name": row["activity_name"] or _display_sport(row),
                         "date": short_date(day), "time": clock, "sport": _display_sport(row),
                         "category": _sport(row), "planned_intent": row["planned_intent"], "rpe": row["rpe"],
                         "rateable": row["type"].strip().lower() != "walking" and
                         _sport(row) not in ("excluded", "mobility")},
            "prev_id": prev_row[0] if prev_row else None, "next_id": next_row[0] if next_row else None,
            "stats": _stats(row, session, cadence, effort_label), "opinion": opinion,
            "opinion_meta": dict(opinion_row) if opinion_row else None,
            "zones": sorted(zones, key=lambda zone: zone["name"][:2], reverse=True),
            "laps": [] if whole_lap else laps, "hr_chart": hr_chart,
            "similar": _similar(settings, activity_id), "intents": INTENTS,
            "ask_suggestions": RUN_SUGGESTIONS if _sport(row) == "running" else OTHER_SUGGESTIONS,
            "sync": sync_label(settings, _local_day(settings))}


def set_planned_intent(settings: Settings, activity_id: int, intent: str | None) -> None:
    if intent not in (None, *INTENTS):
        raise ValueError("Invalid planned intent")
    with sqlite3.connect(settings.db_path) as connection:
        changed = connection.execute("UPDATE activities SET planned_intent=? WHERE id=? AND user_id=?",
                                     (intent, activity_id, settings.default_user_id)).rowcount
        if changed != 1:
            raise ValueError("Activity not found")


class _CountedLLM:
    def __init__(self, llm: Any, settings: Settings) -> None:
        self.llm = llm
        self.counter = CoachAgent(settings, llm, settings.default_user_id)

    def generate_json(self, system_prompt: str, user_prompt: str, response_schema: Any = None) -> dict[str, Any]:
        self.counter._count_request()
        return self.llm.generate_json(system_prompt, user_prompt, response_schema=response_schema)


def generate_opinion(settings: Settings, activity_id: int, *, regenerate: bool, llm: Any = None) -> None:
    if settings.llm_provider in ("openai", "chatgpt") and not (
            settings.allow_remote_llm and settings.remote_athlete_data_approved):
        raise PermissionError("Remote coaching is disabled until athlete-data sharing is approved in .env")
    client = llm or get_llm_client(settings.llm_provider, settings.openai_api_key, settings.openai_model,
                                   settings.ollama_base_url, settings.ollama_model)
    engine = create_engine(settings.db_url)
    try:
        with _user_lock(settings.db_path, settings.default_user_id):
            with Session(engine) as session:
                user = session.get(User, settings.default_user_id)
                if user is None:
                    raise ValueError("Athlete not found")
                ActivityCoachingService(settings, _CountedLLM(client, settings)).generate(
                    session, user=user, activity_id=activity_id, regenerate=regenerate)
                session.commit()
    finally:
        engine.dispose()


def add_recommendation(settings: Settings, activity_id: int, index: int) -> list[dict[str, Any]]:
    if index < 0:
        raise ValueError("Invalid recommendation")
    with _db(settings.db_path) as connection:
        activity = connection.execute("SELECT date FROM activities WHERE id=? AND user_id=?",
                                      (activity_id, settings.default_user_id)).fetchone()
        row = connection.execute("SELECT * FROM activity_coaching_insights WHERE activity_id=? AND user_id=?",
                                 (activity_id, settings.default_user_id)).fetchone()
    if activity is None or row is None:
        raise ValueError("Opinion not found")
    opinion = load_opinion(dict(row))
    if index >= len(opinion.recommendations) or opinion.recommendations[index].action != "add_to_plan":
        raise ValueError("Recommendation cannot be added")
    facts = [{"id": f"EVIDENCE_{number}", "metric": fact.metric,
              "display": fact.value, "source": fact.source}
             for number, fact in enumerate(opinion.evidence, 1)]
    proposals = propose_opinion_recommendations(
        activity_id, date.fromisoformat(activity["date"]),
        [opinion.recommendations[index].model_dump()], facts,
        settings=settings, user_id=settings.default_user_id)
    if not proposals:
        raise ValueError("No safe plan change is available for that recommendation")
    return proposals


def rate_session(settings: Settings, activity_id: int, rpe: int) -> None:
    engine = create_engine(settings.db_url)
    try:
        with Session(engine) as session:
            rate_activity(session, activity_id, settings.default_user_id, rpe, "web")
            session.commit()
    finally:
        engine.dispose()


def ask_activity(settings: Settings, activity_id: int, question: str, llm: Any = None):
    with _db(settings.db_path) as connection:
        exists = connection.execute("SELECT 1 FROM activities WHERE id=? AND user_id=?",
                                    (activity_id, settings.default_user_id)).fetchone()
    if exists is None:
        raise ValueError("Activity not found")
    return TrainingChatService(settings, llm_client=llm).answer(question, settings.default_user_id, activity_id)
