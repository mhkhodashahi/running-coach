"""Scheduled work; all decisions and plan changes go through existing services."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from time import sleep
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from coach.planning import load_model, propose_week
from coach.proposals import SUPPRESS_PROPOSAL_NOTICE, get_week, list_proposals, monday
from config import Settings
from metrics import get_daily_snapshot
from metrics.sports import sport_category
from services.daily_decision_service import get_or_create_daily_decision
from services.effort_service import dispatch_effort_prompts, unrated_activities
from services.fact_display import signed_delta
from services.import_service import GarminImportService
from services.telegram_service import TelegramService
from worker.messages import (
    OutboundMessage,
    data_update,
    day_review,
    decision_reason,
    morning,
    proposal_items,
    weekly_review,
)
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
    engine = create_engine(settings.db_url)
    try:
        with Session(engine) as session:
            rows = unrated_activities(session, settings.default_user_id, limit=50, now=now,
                                      timezone=settings.local_timezone)
            if day is not None:
                rows = [row for row in rows if row.date == day]
            return [(row.id, f"{sport_category(row.type, row.date)} on "
                     f"{row.date:%a} {row.date.day} {row.date:%b}") for row in rows[:limit]]
    finally:
        engine.dispose()


def morning_payload(settings: Settings, day: date, *, use_llm: bool,
                    now: datetime | None = None) -> OutboundMessage:
    decision = _decision(settings, day, use_llm)
    snapshot = get_daily_snapshot(date.fromisoformat(decision.based_on), database=settings.db_path,
                                  user_id=settings.default_user_id, timezone=settings.local_timezone,
                                  sleep_goal_hours=settings.sleep_goal_hours, hr_zones=settings.hr_zones)
    last_unrated = _unrated(settings, now or datetime.now(ZoneInfo(settings.local_timezone)))
    with sqlite3.connect(settings.db_path) as db:
        known_health_day = db.execute("SELECT 1 FROM health_metrics WHERE user_id=? AND date=? "
                                      "AND sleep_duration IS NOT NULL AND hrv IS NOT NULL",
                                      (settings.default_user_id, decision.based_on)).fetchone() is not None
    return morning(decision, _plan_labels(_planned(settings, day)), snapshot.load.ratio.value,
                   last_unrated[0] if last_unrated else None, public_url=settings.public_url,
                   known_health_day=known_health_day)


def morning_message(settings: Settings, day: date, *, use_llm: bool) -> str:
    return morning_payload(settings, day, use_llm=use_llm).plain


def _no_llm():
    from llm.base import NullLLMClient

    return NullLLMClient()


def day_review_payload(settings: Settings, day: date, *, use_llm: bool = False,
                       now: datetime | None = None) -> OutboundMessage:
    planned = _planned(settings, day)
    with sqlite3.connect(settings.db_path) as db:
        actual = db.execute("SELECT a.id,a.type,a.duration,e.rpe FROM activities a "
                            "LEFT JOIN activity_efforts e ON e.activity_id=a.id "
                            "WHERE a.user_id=? AND a.date=?", (settings.default_user_id, day.isoformat())).fetchall()
    actual = [row for row in actual if sport_category(row[1], day) not in ("excluded", "mobility")
              and row[1].strip().lower() != "walking"]
    completed = [item for item in planned if item["status"] == "done"]
    skipped = [item for item in planned if item["status"] in ("skipped", "planned")]
    extras = [item for item in actual if not any(plan.get("linked_activity_id") == item[0] for plan in completed)]
    tomorrow = day + timedelta(days=1)
    next_plan = _planned(settings, tomorrow)
    decision = _decision(settings, tomorrow, use_llm)
    if any(item["status"] == "planned" and
           _INTENSITY[decision.intensity] < _INTENSITY["hard" if item["intent"] in
           ("tempo", "race", "match", "training") else "easy"] for item in next_plan):
        # get_or_create_daily_decision already creates the conflict proposal; never apply it.
        pass
    labels = [f"{item['sport'].title()} {item['intent']} (planned)" for item in completed]
    labels.extend(f"{sport_category(row[1], day).title()} {round(row[2])} min (extra)"
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
    mix: dict[str, int] = {}
    for raw in raw_types.values():
        sport = sport_category(raw, day)
        if sport in ("excluded", "mobility") or raw.strip().lower() == "walking":
            continue
        mix[sport] = mix.get(sport, 0) + 1
    with sqlite3.connect(settings.db_path) as db:
        latest_health = db.execute("SELECT MAX(date) FROM health_metrics WHERE user_id=? AND date<=? "
                                   "AND hrv IS NOT NULL AND resting_hr IS NOT NULL",
                                   (settings.default_user_id, day.isoformat())).fetchone()[0]
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
            now: datetime, build: Callable[[], str | OutboundMessage],
            send: Callable[[str | OutboundMessage], None] | None = None) -> JobResult:
    if not claim(settings.db_path, settings.default_user_id, job, day, now):
        return JobResult(job, None, False)
    try:
        message = build()
        sent_format = "html"
        if send is not None:
            send(message)
        elif isinstance(message, OutboundMessage):
            sent_format = telegram.send_message(message.html, message.keyboard, message.plain)
        else:
            telegram.send_text(message)
    except Exception as exc:
        # A timeout can mean Telegram accepted the message. Never resend automatically.
        finish(settings.db_path, settings.default_user_id, job, day, now,
               error=telegram.redact(str(exc)))
        return JobResult(job, None, False)
    text = (message.plain if sent_format == "plain" else message.html) if isinstance(message, OutboundMessage) else message
    finish(settings.db_path, settings.default_user_id, job, day, now, message=text)
    return JobResult(job, text, True)


def _late_morning_update(settings: Settings, telegram: TelegramService, day: date,
                         now: datetime, *, use_llm: bool) -> JobResult | None:
    if not health_ready(settings, day):
        return None
    with sqlite3.connect(settings.db_path) as db:
        if db.execute("SELECT 1 FROM job_runs WHERE user_id=? AND job='morning_update' AND run_date=?",
                      (settings.default_user_id, day.isoformat())).fetchone():
            return None
        previous = db.execute("SELECT status,message_text FROM job_runs WHERE user_id=? AND job='morning' "
                              "AND run_date=?", (settings.default_user_id, day.isoformat())).fetchone()
    if not previous or previous[0] != "sent" or "waiting for your data" not in (previous[1] or ""):
        return None
    decision = _decision(settings, day, use_llm)
    old_intensity = "rest" if "<b>Rest day" in previous[1] else "easy"
    if decision.intensity == old_intensity:
        if claim(settings.db_path, settings.default_user_id, "morning_update", day, now):
            finish(settings.db_path, settings.default_user_id, "morning_update", day, now)
        return None
    return deliver(settings, telegram, "morning_update", day, now,
                   lambda: data_update(decision.headline, decision_reason(decision),
                                       illness=decision.rule == "illness_signal"))


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
                               lambda: morning_payload(settings, day, use_llm=bool(pref["morning_llm"]), now=local)))
    update = _late_morning_update(settings, telegram, day, local, use_llm=bool(pref["morning_llm"]))
    if update is not None:
        results.append(update)
    if clock >= pref["day_review_time"]:
        results.append(deliver(settings, telegram, "day_review", day, local,
                               lambda: day_review_payload(settings, day, use_llm=bool(pref["day_llm"]), now=local)))
    if day.weekday() == pref["weekly_weekday"] and clock >= pref["weekly_time"]:
        results.append(deliver(settings, telegram, "weekly_review", day, local,
                               lambda: weekly_payload(settings, day, use_llm=bool(pref["weekly_llm"]))))
    dispatch_effort_prompts(settings, settings.default_user_id, telegram)
    return results
