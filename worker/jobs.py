"""Scheduled work; all decisions and plan changes go through existing services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from time import sleep
from zoneinfo import ZoneInfo

from config import Settings
from db.repositories.worker_state import WorkerJobReadRepository
from db.session import session_scope
from services.effort_service import dispatch_effort_prompts
from services.import_service import GarminImportService
from services.review_service import _decision as _decision
from services.review_service import _no_llm as _no_llm
from services.review_service import _plan_labels as _plan_labels
from services.review_service import _planned as _planned
from services.review_service import _unrated as _unrated
from services.review_service import day_review_message as day_review_message
from services.review_service import day_review_payload as day_review_payload
from services.review_service import morning_message as morning_message
from services.review_service import morning_payload as morning_payload
from services.review_service import weekly_message as weekly_message
from services.review_service import weekly_payload as weekly_payload
from services.telegram_service import TelegramService
from worker.backup import daily_backup
from worker.health import health_problems
from worker.messages import (
    OutboundMessage,
    data_update,
    decision_reason,
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
    with session_scope(settings.db_url) as session:
        return WorkerJobReadRepository(session).health_ready(settings.default_user_id, day)


def sync(settings: Settings) -> None:
    with session_scope(settings.db_url) as session:
        GarminImportService().sync_garmin(session, settings.default_user_id,
                                          days=settings.garmin_sync_days,
                                          health_days=settings.garmin_health_sync_days)


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
                            settings.ollama_base_url, settings.ollama_model, settings=settings)
    if isinstance(client, NullLLMClient):
        return 0
    agent = CoachAgent(settings, client, settings.default_user_id)

    class MeteredClient:
        def generate_json(self, system_prompt, user_prompt, response_schema=None):
            agent._count_request()
            return client.generate_json(system_prompt, user_prompt, response_schema)

    with session_scope(settings.db_url) as session:
        candidates = WorkerJobReadRepository(session).pending_running_opinions(
            settings.default_user_id, day - timedelta(days=7), day)
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
    with session_scope(settings.db_url) as session:
        repository = WorkerJobReadRepository(session)
        if repository.has_job(settings.default_user_id, "morning_update", day):
            return None
        previous = repository.job_message(settings.default_user_id, "morning", day)
    if not previous or previous["status"] != "sent" or not any(
        marker in (previous["message_text"] or "") for marker in ("Provisional:", "waiting for your data")
    ):
        return None
    decision = _decision(settings, day, use_llm)
    old_intensity = "rest" if "Rest today" in previous["message_text"] else "easy"
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
    if pref.get("suggest_memories_llm"):
        from worker.memory import suggest_from_idle_chat
        suggest_from_idle_chat(settings, local)
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
    if clock >= MORNING_START:
        with session_scope(settings.db_url) as session:
            synced_today = WorkerJobReadRepository(session).has_completed_sync_today(
                settings.default_user_id, day)
        if synced_today and claim(settings.db_path, settings.default_user_id, "daily_backup", day, local):
            try:
                daily_backup(settings.db_path, settings.backup_dir, day, settings.base_dir)
            except Exception as exc:
                finish(settings.db_path, settings.default_user_id, "daily_backup", day, local,
                       error=telegram.redact(str(exc)))
            else:
                finish(settings.db_path, settings.default_user_id, "daily_backup", day, local)
    if settings.auto_opinions:
        generate_pending_opinions(settings, day, local)
    if not telegram.configured or pref["paused"] or in_quiet_hours(local, pref["quiet_start"], pref["quiet_end"]):
        health_problems(settings.db_path, settings.default_user_id, local, settings.local_timezone)
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
    for problem in health_problems(settings.db_path, settings.default_user_id, local, settings.local_timezone):
        results.append(deliver(settings, telegram, f"health-alert-{problem.code}", day, local,
                               lambda message=problem.text: message))
    return results
