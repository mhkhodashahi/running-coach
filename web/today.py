"""Prepare Today data from the existing decision, metrics, plan and effort services."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from coach.planning import propose_week
from config import Settings
from db.repositories.today_view import TodayViewRepository
from db.session import session_scope
from metrics import get_daily_snapshot
from metrics.sports import RECOMMENDABLE_SPORTS, sport_category
from services.coach_opinion import load_opinion
from services.daily_decision_service import get_or_create_daily_decision, set_athlete_choice
from services.effort_service import rate_activity, unrated_activities
from services.morning_brief import read_brief
from services.timeline_notes import read_notes
from services.weekly_plan_service import get_weekly_plan
from web.charts import load_bars, readiness_ring, sparkline
from web.formatting import (
    activity_distance,
    activity_duration,
    delta,
    metric,
    short_date,
    sleep_hours,
    sync_time,
)
from web.view_models.morning import brief_card, last_session
from web.view_models.today import (
    TODAY_FOLLOW_UPS,
    call_headline,
    coach_evidence,
    coach_heading,
    completed_plan_today,
    dial_models,
    display_decision_text,
    display_duration,
    purpose_line,
    week_strip,
    workout_model,
)


def sync_label(settings: Settings, day: date) -> str:
    with session_scope(f"sqlite:///file:{settings.db_path.resolve()}?mode=ro&uri=true") as session:
        last_sync = TodayViewRepository(session).sync_time(settings.default_user_id)
    return sync_time(last_sync, day, settings.local_timezone)


def today_context(settings: Settings, *, day: date, llm: Any = None) -> dict[str, Any]:
    user_id = settings.default_user_id
    decision = get_or_create_daily_decision(day, settings=settings, user_id=user_id, llm=llm)
    snapshot = get_daily_snapshot(date.fromisoformat(decision.based_on), database=settings.db_path, user_id=user_id,
                                  timezone=settings.local_timezone, sleep_goal_hours=settings.sleep_goal_hours,
                                  hr_zones=settings.hr_zones)
    current = {name: item.value for name, item in snapshot.current_health}
    baselines = {(item.field, item.days): item.mean.value for item in snapshot.baselines}
    sync = sync_label(settings, day)
    morning = brief_card(read_brief(settings.db_path, user_id, day), sync)
    timeline_notes = read_notes(settings.db_path, user_id, day - timedelta(days=14), day)
    with session_scope(f"sqlite:///file:{settings.db_path.resolve()}?mode=ro&uri=true") as session:
        source = TodayViewRepository(session).health_context(
            user_id, date.fromisoformat(decision.based_on), day + timedelta(days=1), day)
    health = source["body_battery"]
    body_history = source["body_history"]
    trend_rows = source["trend_rows"]
    rows = source["activities"]
    latest_rows = source["recent_sessions"]
    recent = []
    for row in latest_rows:
        item = dict(row)
        item["opinion"] = load_opinion(item) if item["payload_json"] else None
        session = next((part for part in snapshot.sessions if part.activity_id == item["id"]), None)
        item["load"] = session.load.value if session else None
        recent.append(item)
    last = last_session(recent, datetime.now(ZoneInfo(settings.local_timezone)))
    if last and last["load"] is None:
        activity_day = date.fromisoformat(next(item["date"] for item in recent if item["id"] == last["id"]))
        activity_snapshot = get_daily_snapshot(activity_day, database=settings.db_path, user_id=user_id,
                                               timezone=settings.local_timezone,
                                               sleep_goal_hours=settings.sleep_goal_hours, hr_zones=settings.hr_zones)
        activity_session = next((item for item in activity_snapshot.sessions
                                 if item.activity_id == last["id"]), None)
        if activity_session and activity_session.load.value is not None:
            last["load"] = f"{round(activity_session.load.value)} load"
    sessions = {session.activity_id: session for session in snapshot.sessions}
    activities = []
    for row in rows:
        sport = sport_category(row["type"], day)
        if sport not in RECOMMENDABLE_SPORTS:
            continue
        session = sessions.get(row["id"])
        activities.append({"id": row["id"], "date": short_date(row["date"]),
                           "sport": row["type"].replace("_", " ").title(),
                           "distance": activity_distance(row["distance"]) if sport == "running" else "—",
                           "duration": activity_duration(row["duration"]),
                           "zones": [(zone.name, zone.percent.value or 0) for zone in session.zones] if session else []})
        if len(activities) == 5:
            break
    # Daily sport loads are already computed by the metrics engine; aggregate all sports by date.
    daily_values: dict[str, list[float | None]] = {}
    for item in snapshot.sport_loads:
        if item.period == "daily" and item.sport not in ("excluded", "mobility"):
            key = item.load.provenance.window_end
            daily_values.setdefault(key, []).append(item.load.value)
    daily = {key: sum(values) if values and all(value is not None for value in values) else None
             for key, values in daily_values.items()}
    bars = [((day - timedelta(days=offset)).isoformat(), daily.get((day - timedelta(days=offset)).isoformat()))
            for offset in range(13, -1, -1)]
    plan = get_weekly_plan(day, settings=settings, user_id=user_id)
    plan_sessions = [{**item, "date_label": short_date(item["date"]),
                      "duration_label": display_duration(item["duration_min"])} for item in plan["sessions"]]
    recommendations = decision.sports
    body_values = [row["body_battery"] for row in body_history]
    body_baseline = (sum(body_values) / len(body_values)) if len(body_values) >= 4 else None
    with session_scope(settings.db_url) as session:
        pending = unrated_activities(session, user_id, limit=1,
                                     now=datetime.now(ZoneInfo(settings.local_timezone)),
                                     timezone=settings.local_timezone)
        unrated = pending[0] if pending else None
    week_start = day - timedelta(days=day.weekday())
    week_activities = [{"id": row["id"], "date": row["date"][:10],
                        "sport": sport_category(row["type"], day)} for row in rows
                       if week_start.isoformat() <= row["date"][:10] and
                       sport_category(row["type"], day) in RECOMMENDABLE_SPORTS]
    unrated_id = unrated.id if unrated else None
    from coach.planning import load_model
    from coach.proposals import monday

    week_start = monday(day)
    load_reference = load_model(settings.db_path, user_id, week_start, settings).previous_weekly_average
    weekly_actual = [item.load.value for item in snapshot.sessions
                     if week_start.isoformat() <= item.day <= day.isoformat()
                     and item.sport not in ("walking", "excluded", "mobility")]
    weekly_load = sum(weekly_actual) if all(value is not None for value in weekly_actual) else None
    dials = dial_models(decision.readiness, current.get("sleep_duration"),
                        baselines.get(("sleep_duration", 28)), weekly_load,
                        load_reference, sync)
    workout = workout_model(decision, plan_sessions)
    done_today = completed_plan_today(day, plan_sessions)
    if done_today:
        workout = None
    return {"decision": decision, "ring": readiness_ring(decision.readiness), "sync": sync,
            "morning_card": morning, "last_session": last,
            "timeline_notes": timeline_notes,
            "day": day, "day_label": short_date(day), "based_on_label": short_date(decision.based_on),
            "recommendations": recommendations, "readiness": metric(decision.readiness),
            "tiles": [
                {"label": "Resting HR", "value": metric(current.get("resting_hr"), "bpm"),
                 "baseline": metric(baselines.get(("resting_hr", 7)), "bpm"),
                 "delta": delta(current.get("resting_hr"), baselines.get(("resting_hr", 7)), "bpm"),
                 "sparkline": sparkline([row["resting_hr"] for row in reversed(trend_rows)], "Resting HR", "heart",
                                        baselines.get(("resting_hr", 7)))},
                {"label": "HRV", "value": metric(current.get("hrv"), "ms"),
                 "baseline": metric(baselines.get(("hrv", 28)), "ms"),
                 "delta": delta(current.get("hrv"), baselines.get(("hrv", 28)), "ms"),
                 "sparkline": sparkline([row["hrv"] for row in reversed(trend_rows)], "HRV", "sleep",
                                        baselines.get(("hrv", 28)))},
                {"label": "Sleep", "value": sleep_hours(current.get("sleep_duration")),
                 "baseline": sleep_hours(baselines.get(("sleep_duration", 28))),
                 "delta": delta(current.get("sleep_duration"), baselines.get(("sleep_duration", 28)), "sleep"),
                 "sparkline": sparkline([row["sleep_duration"] for row in reversed(trend_rows)], "Sleep", "sleep",
                                        baselines.get(("sleep_duration", 28)))},
                {"label": "Body Battery", "value": metric(health),
                 "baseline": metric(body_baseline),
                 "delta": delta(health, body_baseline, ""),
                 "sparkline": sparkline([row["body_battery"] for row in reversed(trend_rows)], "Body Battery", "muted",
                                        body_baseline)},
            ], "load_chart": load_bars(bars, snapshot.load.chronic.value / 7
                                       if snapshot.load.chronic.value is not None else None, sync,
                                       day.isoformat()),
            "load_ratio": metric(snapshot.load.ratio.value, precision=2),
            "load_status": "Above usual range" if snapshot.load.ratio.value is not None and snapshot.load.ratio.value > 1.3
                           else "Below usual range" if snapshot.load.ratio.value is not None and snapshot.load.ratio.value < 0.8
                           else "In usual range" if snapshot.load.ratio.value is not None else None,
            "plan": plan_sessions, "activities": activities,
            "team_rest_caution": any(item["label"] == "Skip team training or attend skills only"
                                     for item in decision.team_options),
            "unrated": {"id": unrated.id, "sport": unrated.type.replace("_", " ").title(),
                        "date": short_date(unrated.date)} if unrated else None,
            "dials": dials,
            "week_strip": week_strip(day, plan_sessions, week_activities, unrated_id, workout),
            "workout": workout, "call_headline": "Done for today" if done_today else
            call_headline(decision.intensity, workout),
            "done_today": bool(done_today),
            "coach_heading": "Why you're done for today" if done_today else coach_heading(decision.intensity, workout),
            "coach_evidence": coach_evidence(decision), "coach_follow_ups": TODAY_FOLLOW_UPS,
            "purpose": (f"{done_today['sport'].capitalize()} completed." if done_today else
                        purpose_line(workout, dials, decision.intensity) +
                        (" I shortened the suggestion to fit the weekly limit."
                         if decision.weekly_limit_reason == "shortened to fit the weekly limit" else
                         " There is no room for a hard session within the weekly limit."
                         if decision.weekly_limit_reason == "easy: no room in the weekly limit" else "")),
            "decision_text": display_decision_text(decision.explanation)}


def choose_intensity(settings: Settings, day: date, choice: str | None) -> None:
    set_athlete_choice(day, choice, settings=settings)


def save_rating(settings: Settings, activity_id: int, rpe: int) -> None:
    with session_scope(settings.db_url) as session:
        rate_activity(session, activity_id, settings.default_user_id, rpe, "web")


def create_week_proposal(settings: Settings, day: date, llm: Any = None) -> dict[str, Any]:
    """Propose, but never apply, a plan for the current week."""
    return propose_week(day, settings=settings, llm=llm, today=day)
