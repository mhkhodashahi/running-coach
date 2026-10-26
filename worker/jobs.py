"""Scheduled work; all decisions and plan changes go through existing services."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from time import sleep
from zoneinfo import ZoneInfo

from coach.planning import load_model, propose_week
from coach.proposals import SUPPRESS_PROPOSAL_NOTICE, get_week, list_proposals, monday
from config import Settings
from metrics import get_daily_snapshot
from metrics.sports import sport_category
from services.daily_decision_service import get_or_create_daily_decision
from services.effort_service import dispatch_effort_prompts
from services.import_service import GarminImportService
from services.telegram_service import TelegramService
from worker.state import claim, finish, in_quiet_hours, preferences

MORNING_START = "05:30"
MORNING_POLL_MINUTES = 20
_INTENSITY = {"rest": 0, "easy": 1, "hard": 2}


@dataclass(frozen=True)
class JobResult:
    job: str
    message: str | None
    sent: bool


def health_ready(settings: Settings, day: date) -> bool:
    with sqlite3.connect(settings.db_path) as db:
        row = db.execute("SELECT sleep_duration,hrv FROM health_metrics WHERE user_id=? AND date=?",
                         (settings.default_user_id, day.isoformat())).fetchone()
    return bool(row and row[0] is not None and row[1] is not None)


def _planned(settings: Settings, day: date) -> list[dict]:
    week = get_week(settings.db_path, settings.default_user_id, monday(day))
    return [item for item in week["sessions"] if item["date"] == day.isoformat()]


def morning_message(settings: Settings, day: date, *, use_llm: bool) -> str:
    token = SUPPRESS_PROPOSAL_NOTICE.set(True)
    try:
        decision = get_or_create_daily_decision(day, settings=settings,
                                                llm=None if use_llm else _no_llm())
    finally:
        SUPPRESS_PROPOSAL_NOTICE.reset(token)
    lines = [decision.headline, decision.explanation,
             f"Readiness: {round(decision.readiness) if decision.readiness is not None else 'No data'}"]
    if decision.provisional:
        lines.append(f"Provisional, based on {decision.based_on}.")
    if decision.sports:
        top = decision.sports[0]
        lines.append(f"Recommended: {top['sport'].title()} - {top['session']['structure']}.")
    planned = _planned(settings, day)
    lines.append("Planned: " + (", ".join(f"{item['sport']} {item['intent']}" for item in planned)
                                 if planned else "nothing planned"))
    return "\n".join(lines) + f"\nToday: {settings.web_public_url}/"


def _no_llm():
    from llm.base import NullLLMClient

    return NullLLMClient()


def day_review_message(settings: Settings, day: date, *, use_llm: bool = False) -> str:
    planned = _planned(settings, day)
    with sqlite3.connect(settings.db_path) as db:
        actual = db.execute("SELECT a.id,a.type,e.rpe FROM activities a "
                            "LEFT JOIN activity_efforts e ON e.activity_id=a.id "
                            "WHERE a.user_id=? AND a.date=?", (settings.default_user_id, day.isoformat())).fetchall()
    actual = [row for row in actual if sport_category(row[1], day) not in ("excluded", "mobility")
              and row[1].strip().lower() != "walking"]
    completed = [item for item in planned if item["status"] == "done"]
    skipped = [item for item in planned if item["status"] == "skipped"]
    extras = [item for item in actual if not any(plan.get("linked_activity_id") == item[0] for plan in completed)]
    tomorrow = day + timedelta(days=1)
    next_plan = _planned(settings, tomorrow)
    token = SUPPRESS_PROPOSAL_NOTICE.set(True)
    try:
        decision = get_or_create_daily_decision(tomorrow, settings=settings,
                                                llm=None if use_llm else _no_llm())
    finally:
        SUPPRESS_PROPOSAL_NOTICE.reset(token)
    if any(item["status"] == "planned" and
           _INTENSITY[decision.intensity] < _INTENSITY["hard" if item["intent"] in
           ("tempo", "race", "match", "training") else "easy"] for item in next_plan):
        # get_or_create_daily_decision already creates the conflict proposal; never apply it.
        pass
    previous = get_daily_snapshot(day - timedelta(days=1), database=settings.db_path,
                                  user_id=settings.default_user_id, timezone=settings.local_timezone,
                                  sleep_goal_hours=settings.sleep_goal_hours, hr_zones=settings.hr_zones)
    current = get_daily_snapshot(day, database=settings.db_path,
                                 user_id=settings.default_user_id, timezone=settings.local_timezone,
                                 sleep_goal_hours=settings.sleep_goal_hours, hr_zones=settings.hr_zones)
    before = previous.readiness.score.value
    today_readiness = current.readiness.score.value
    trend = (f"Readiness was {round(before)} yesterday and is {round(today_readiness)} today."
             if before is not None and today_readiness is not None else "Readiness trend: not enough data.")
    return (f"Day review for {day.isoformat()}: {len(completed)} done, {len(skipped)} skipped, "
            f"{len(extras)} extra. {sum(row[2] is None for row in actual)} unrated. {trend}\n"
            f"Tomorrow: {', '.join(item['sport'] + ' ' + item['intent'] for item in next_plan) or 'nothing planned'}. "
            f"Decision: {decision.intensity}.\nPlan: {settings.web_public_url}/plan")


def weekly_message(settings: Settings, day: date, *, use_llm: bool) -> str:
    start = monday(day) + timedelta(days=7)
    existing = [item for item in list_proposals(settings.db_path, settings.default_user_id, start)
                if item["status"] == "pending"]
    if existing:
        summary = existing[0]["summary"]
    else:
        try:
            token = SUPPRESS_PROPOSAL_NOTICE.set(True)
            try:
                proposal = propose_week(start, settings=settings, today=day, code_only=not use_llm)
            finally:
                SUPPRESS_PROPOSAL_NOTICE.reset(token)
            summary = proposal.get("summary", "No safe change this week")
        except (ValueError, RuntimeError, PermissionError):
            summary = "A weekly proposal could not be prepared. Review the plan in the app."
    previous = get_week(settings.db_path, settings.default_user_id, monday(day))
    completed = sum(item["status"] == "done" for item in previous["sessions"])
    snapshot = get_daily_snapshot(day, database=settings.db_path, user_id=settings.default_user_id,
                                  timezone=settings.local_timezone, sleep_goal_hours=settings.sleep_goal_hours,
                                  hr_zones=settings.hr_zones)
    week_start = monday(day)
    with sqlite3.connect(settings.db_path) as db:
        raw_types = {identifier: raw for identifier, raw in db.execute(
            "SELECT id,type FROM activities WHERE user_id=? AND date>=? AND date<=?",
            (settings.default_user_id, week_start.isoformat(), day.isoformat()))}
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
    mix = ", ".join(f"{sport} {round(load)}" for sport, load in sorted(sport_load.items())) or "no training load"
    trend = (f"Readiness {round(snapshot.readiness.score.value)}." if snapshot.readiness.score.value is not None
             else "Readiness unavailable.")
    return (f"Weekly review: {total} TRIMP vs cap {round(cap) if cap is not None else 'not available'}; "
            f"{completed} of {len(previous['sessions'])} planned sessions done. "
            f"Sport mix: {mix}. {trend} Next week: {summary}. "
            f"Review in the app: {settings.web_public_url}/plan")


def sync(settings: Settings) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = create_engine(settings.db_url)
    try:
        with Session(engine) as session, session.begin():
            GarminImportService().sync_garmin(session, settings.default_user_id,
                                              days=settings.garmin_sync_days,
                                              health_days=settings.garmin_health_sync_days)
    finally:
        engine.dispose()


def generate_pending_opinions(settings: Settings, day: date, now: datetime) -> int:
    """Attempt recent unreviewed runs once; count each provider request."""
    if not settings.auto_opinions:
        return 0
    if settings.llm_provider in ("openai", "chatgpt") and not (
            settings.allow_remote_llm and settings.remote_athlete_data_approved):
        return 0
    from coach.agent import CoachAgent
    from llm.base import NullLLMClient
    from llm.factory import get_llm_client
    from services.activity_coaching_service import ActivityCoachingService

    client = get_llm_client(settings.llm_provider, settings.openai_api_key, settings.openai_model,
                            settings.ollama_base_url, settings.ollama_model)
    if isinstance(client, NullLLMClient):
        return 0
    agent = CoachAgent(settings, client, settings.default_user_id)

    class MeteredClient:
        def generate_json(self, system_prompt, user_prompt, response_schema=None):
            agent._count_request()
            return client.generate_json(system_prompt, user_prompt, response_schema)

    with sqlite3.connect(settings.db_path) as db:
        candidates = [(row[0], date.fromisoformat(row[1])) for row in db.execute(
            "SELECT a.id,a.date FROM activities a LEFT JOIN activity_coaching_insights i ON i.activity_id=a.id "
            "WHERE a.user_id=? AND a.date>=? AND a.date<=? AND lower(a.type) LIKE '%running%' "
            "AND i.id IS NULL ORDER BY a.id",
            (settings.default_user_id, (day - timedelta(days=7)).isoformat(), day.isoformat()))]
    count = 0
    for activity_id, activity_day in candidates:
        job = f"opinion-{activity_id}"
        if not claim(settings.db_path, settings.default_user_id, job, activity_day, now):
            continue
        try:
            ActivityCoachingService(settings, llm_client=MeteredClient()).generate_for_activity(
                user_id=settings.default_user_id, activity_id=activity_id)
        except (ValueError, PermissionError, RuntimeError) as exc:
            finish(settings.db_path, settings.default_user_id, job, activity_day, now,
                   error=str(exc))
            continue
        finish(settings.db_path, settings.default_user_id, job, activity_day, now)
        count += 1
    return count


def retry_sync(operation: Callable[[], None], pause: Callable[[float], None] = sleep) -> None:
    """Retry transient Garmin failures inside one claimed slot."""
    for attempt in range(3):
        try:
            operation()
            return
        except (OSError, RuntimeError):
            if attempt == 2:
                raise
            pause(2 ** attempt)


def deliver(settings: Settings, telegram: TelegramService, job: str, day: date,
            now: datetime, build: Callable[[], str],
            send: Callable[[str], None] | None = None) -> JobResult:
    if not claim(settings.db_path, settings.default_user_id, job, day, now):
        return JobResult(job, None, False)
    try:
        message = build()
        (send or telegram.send_text)(message)
    except Exception as exc:
        # A timeout can mean Telegram accepted the message. Never resend automatically.
        finish(settings.db_path, settings.default_user_id, job, day, now,
               error=telegram.redact(str(exc)))
        return JobResult(job, None, False)
    finish(settings.db_path, settings.default_user_id, job, day, now, message=message)
    return JobResult(job, message, True)


def _send_with_proposal(settings: Settings, telegram: TelegramService, day: date, text: str) -> None:
    pending = [row for row in list_proposals(settings.db_path, settings.default_user_id, monday(day))
               if row["status"] == "pending"]
    if pending:
        telegram.send_proposal_prompt(text, pending[0]["id"])
    else:
        telegram.send_text(text)


def tick(settings: Settings, now: datetime, telegram: TelegramService,
         *, sync_job: Callable[[], None] | None = None) -> list[JobResult]:
    """Run jobs due at this local instant; inject clock/transport in tests."""
    local = now.astimezone(ZoneInfo(settings.local_timezone))
    day = local.date()
    clock = local.strftime("%H:%M")
    pref = preferences(settings.db_path, settings.default_user_id)
    results = []
    sync_job = sync_job or (lambda: sync(settings))
    morning_sync = (MORNING_START <= clock < pref["morning_latest"] and
                    (local.hour * 60 + local.minute - 5 * 60 - 30) % MORNING_POLL_MINUTES < 5 and
                    not health_ready(settings, day))
    periodic_sync = local.hour % settings.sync_interval_hours == 0 and local.minute < 5
    if morning_sync or periodic_sync:
        slot = f"sync-{local.hour:02d}-{(local.minute // 20) * 20:02d}" if morning_sync else f"sync-{local.hour:02d}"
        if claim(settings.db_path, settings.default_user_id, slot, day, local):
            try:
                retry_sync(sync_job)
            except Exception as exc:
                finish(settings.db_path, settings.default_user_id, slot, day, local,
                       error=telegram.redact(str(exc)))
            else:
                finish(settings.db_path, settings.default_user_id, slot, day, local)
    if settings.auto_opinions:
        generate_pending_opinions(settings, day, local)
    if not telegram.configured or pref["paused"] or in_quiet_hours(local, pref["quiet_start"], pref["quiet_end"]):
        return results
    if pref["morning_enabled"] and MORNING_START <= clock and (
            health_ready(settings, day) or clock >= pref["morning_latest"]):
        results.append(deliver(settings, telegram, "morning", day, local,
                               lambda: morning_message(settings, day, use_llm=bool(pref["morning_llm"]))))
    if clock >= pref["day_review_time"]:
        results.append(deliver(settings, telegram, "day_review", day, local,
                               lambda: day_review_message(settings, day, use_llm=bool(pref["day_llm"])),
                               lambda text: _send_with_proposal(settings, telegram, day, text)))
    if day.weekday() == pref["weekly_weekday"] and clock >= pref["weekly_time"]:
        results.append(deliver(settings, telegram, "weekly_review", day, local,
                               lambda: weekly_message(settings, day, use_llm=bool(pref["weekly_llm"])),
                               lambda text: _send_with_proposal(settings, telegram,
                                                                 monday(day) + timedelta(days=7), text)))
    dispatch_effort_prompts(settings, settings.default_user_id, telegram)
    return results
