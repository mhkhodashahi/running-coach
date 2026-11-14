"""Shared guarded review composition for manual digests and scheduled jobs."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from coach.load_model import load_model
from coach.planning import propose_week
from coach.proposals import SUPPRESS_PROPOSAL_NOTICE, get_week, list_proposals, monday
from config import Settings
from db.repositories.worker_state import WorkerJobReadRepository
from db.session import session_scope
from metrics import get_daily_snapshot
from metrics.sports import sport_category
from services.daily_decision_service import get_or_create_daily_decision
from services.effort_service import unrated_activities
from services.fact_display import signed_delta
from services.morning_brief import get_or_create_brief
from worker.messages import (
    OutboundMessage,
    day_review,
    decision_reason,
    morning_brief,
    proposal_items,
    weekly_review,
)

_INTENSITY = {"rest": 0, "easy": 1, "hard": 2}

def _planned(settings: Settings, day: date) -> list[dict]:
    week = get_week(settings.db_path, settings.default_user_id, monday(day))
    return [item for item in week["sessions"] if item["date"] == day.isoformat()]


def _decision(settings: Settings, day: date, use_llm: bool):
    token = SUPPRESS_PROPOSAL_NOTICE.set(True)
    try:
        return get_or_create_daily_decision(day, settings=settings, llm=None if use_llm else _no_llm())
    finally:
        SUPPRESS_PROPOSAL_NOTICE.reset(token)


def _plan_labels(items: list[dict]) -> list[str]:
    return [f"{item['sport'].title()} {item['intent']} {item['duration_min']} min" for item in items
            if item["status"] != "skipped"]


def _unrated(settings: Settings, now: datetime, *, day: date | None = None,
             limit: int = 1) -> list[tuple[int, str]]:
    with session_scope(settings.db_url) as session:
        rows = unrated_activities(session, settings.default_user_id, limit=50, now=now,
                                  timezone=settings.local_timezone)
        if day is not None:
            rows = [row for row in rows if row.date == day]
        return [(row.id, f"{sport_category(row.type, row.date)} on "
                 f"{row.date:%a} {row.date.day} {row.date:%b}") for row in rows[:limit]]


def morning_payload(settings: Settings, day: date, *, use_llm: bool,
                    now: datetime | None = None) -> OutboundMessage:
    decision = _decision(settings, day, False)
    brief = get_or_create_brief(settings, day, decision, use_ai=use_llm)
    return morning_brief(brief, public_url=settings.public_url)


def morning_message(settings: Settings, day: date, *, use_llm: bool) -> str:
    return morning_payload(settings, day, use_llm=use_llm).plain


def _no_llm():
    from llm.base import NullLLMClient

    return NullLLMClient()


def day_review_payload(settings: Settings, day: date, *, use_llm: bool = False,
                       now: datetime | None = None) -> OutboundMessage:
    planned = _planned(settings, day)
    with session_scope(settings.db_url) as session:
        actual = WorkerJobReadRepository(session).day_activities(settings.default_user_id, day)
    actual = [row for row in actual if sport_category(row["type"], day) not in ("excluded", "mobility")
              and row["type"].strip().lower() != "walking"]
    completed = [item for item in planned if item["status"] == "done"]
    skipped = [item for item in planned if item["status"] in ("skipped", "planned")]
    extras = [item for item in actual if not any(plan.get("linked_activity_id") == item["id"] for plan in completed)]
    tomorrow = day + timedelta(days=1)
    next_plan = _planned(settings, tomorrow)
    decision = _decision(settings, tomorrow, use_llm)
    if any(item["status"] == "planned" and
           _INTENSITY[decision.intensity] < _INTENSITY["hard" if item["intent"] in
           ("tempo", "race", "match", "training") else "easy"] for item in next_plan):
        # get_or_create_daily_decision already creates the conflict proposal; never apply it.
        pass
    labels = [f"{item['sport'].title()} {item['intent']} (planned)" for item in completed]
    labels.extend(f"{sport_category(row['type'], day).title()} {round(row['duration'])} min (extra)"
                  for row in extras)
    return day_review(day, labels, _plan_labels(skipped),
                      _unrated(settings, now or datetime.now(ZoneInfo(settings.local_timezone)), day=day, limit=2),
                      _plan_labels(next_plan), decision.intensity, decision_reason(decision),
                      public_url=settings.public_url)


def day_review_message(settings: Settings, day: date, *, use_llm: bool = False) -> str:
    return day_review_payload(settings, day, use_llm=use_llm).plain


def weekly_payload(settings: Settings, day: date, *, use_llm: bool) -> OutboundMessage:
    start = monday(day) + timedelta(days=7)
    existing = [item for item in list_proposals(settings.db_path, settings.default_user_id, start)
                if item["status"] == "pending"]
    if existing:
        summary = existing[0]["summary"]
        proposal_id = existing[0]["id"]
        changes = existing[0]["changes"]
    else:
        try:
            token = SUPPRESS_PROPOSAL_NOTICE.set(True)
            try:
                proposal = propose_week(start, settings=settings, today=day, code_only=not use_llm)
            finally:
                SUPPRESS_PROPOSAL_NOTICE.reset(token)
            summary = proposal.get("summary", "No safe change this week")
            proposal_id = proposal.get("id") if proposal.get("status") == "pending" else None
            changes = proposal.get("changes", [])
        except (ValueError, RuntimeError, PermissionError):
            summary = "A weekly proposal could not be prepared. Review the plan in the app."
            proposal_id = None
            changes = []
    previous = get_week(settings.db_path, settings.default_user_id, monday(day))
    completed = sum(item["status"] == "done" for item in previous["sessions"])
    snapshot = get_daily_snapshot(day, database=settings.db_path, user_id=settings.default_user_id,
                                  timezone=settings.local_timezone, sleep_goal_hours=settings.sleep_goal_hours,
                                  hr_zones=settings.hr_zones)
    week_start = monday(day)
    with session_scope(settings.db_url) as session:
        raw_types = WorkerJobReadRepository(session).activity_types(
            settings.default_user_id, week_start, day)
    sport_load: dict[str, float] = {}
    for item in snapshot.sessions:
        if item.day < week_start.isoformat() or item.load.value is None:
            continue
        raw = raw_types.get(item.activity_id, "")
        sport = sport_category(raw, day)
        if sport in ("excluded", "mobility") or raw.strip().lower() == "walking":
            continue
        sport_load[sport] = sport_load.get(sport, 0) + item.load.value
    total = round(sum(sport_load.values()))
    cap = load_model(settings.db_path, settings.default_user_id, week_start, settings).cap
    mix: dict[str, int] = {}
    for raw in raw_types.values():
        sport = sport_category(raw, day)
        if sport in ("excluded", "mobility") or raw.strip().lower() == "walking":
            continue
        mix[sport] = mix.get(sport, 0) + 1
    with session_scope(settings.db_url) as session:
        latest_health = WorkerJobReadRepository(session).latest_health_day(settings.default_user_id, day)
    health_snapshot = (get_daily_snapshot(date.fromisoformat(latest_health), database=settings.db_path,
                                          user_id=settings.default_user_id, timezone=settings.local_timezone,
                                          sleep_goal_hours=settings.sleep_goal_hours, hr_zones=settings.hr_zones)
                       if latest_health and latest_health != day.isoformat() else snapshot)
    current = dict(health_snapshot.current_health)
    baselines = {(item.field, item.days): item.mean.value for item in health_snapshot.baselines}
    hrv = current.get("hrv")
    rhr = current.get("resting_hr")
    hrv_base = baselines.get(("hrv", 28))
    rhr_base = baselines.get(("resting_hr", 7))
    trend = (f"HRV {signed_delta(hrv.value - hrv_base, 'ms')} · "
             f"resting HR {signed_delta(rhr.value - rhr_base, 'bpm')} vs baseline"
             if hrv and rhr and hrv.value is not None and rhr.value is not None and
             hrv_base is not None and rhr_base is not None else "Recovery trend: not enough data")
    summary = proposal_items(changes) if changes else "; ".join(summary.split(";")[:4])
    return weekly_review(week_start, total, cap, completed, len(previous["sessions"]), mix,
                         trend, summary, proposal_id, public_url=settings.public_url)


def weekly_message(settings: Settings, day: date, *, use_llm: bool) -> str:
    return weekly_payload(settings, day, use_llm=use_llm).plain
