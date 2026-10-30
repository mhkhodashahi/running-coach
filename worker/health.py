"""Read-only worker diagnostics and idempotent, actionable alert text."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from worker.state import preferences, worker_running

SYNC_MAX_AGE = timedelta(hours=26)
HEARTBEAT_MAX_AGE = timedelta(minutes=3)


@dataclass(frozen=True)
class HealthProblem:
    code: str
    text: str


def _timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def worker_last_seen(database: Path) -> datetime | None:
    path = database.with_suffix(".worker.lock")
    return datetime.fromtimestamp(path.stat().st_mtime, UTC) if path.exists() else None


def health_problems(database: Path, user_id: int, now: datetime, timezone: str) -> tuple[HealthProblem, ...]:
    """Describe current failures; never expose stored exception text or credentials."""
    local = now.astimezone(ZoneInfo(timezone))
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        sync_row = db.execute("SELECT last_synced_at FROM garmin_sync_status WHERE user_id=?",
                              (user_id,)).fetchone()
        jobs = db.execute("SELECT job,status FROM job_runs WHERE user_id=? AND status!='sending' "
                          "AND job NOT LIKE 'health-alert-%' ORDER BY started_at DESC,id DESC",
                          (user_id,)).fetchall()
        morning = db.execute("SELECT status FROM job_runs WHERE user_id=? AND job='morning' AND run_date=?",
                             (user_id, local.date().isoformat())).fetchone()
    problems: list[HealthProblem] = []
    synced = _timestamp(sync_row[0] if sync_row else None)
    if synced is None or now.astimezone(UTC) - synced.astimezone(UTC) > SYNC_MAX_AGE:
        when = (f" since {synced.astimezone(ZoneInfo(timezone)):%a} "
                f"{synced.astimezone(ZoneInfo(timezone)).day} "
                f"{synced.astimezone(ZoneInfo(timezone)):%b %H:%M}" if synced else " yet")
        problems.append(HealthProblem("sync-stale", "Garmin sync has not worked" + when +
                                      ". Check your Garmin login or run python -m utils.garmin_sync_cli."))
    latest: dict[str, list[str]] = {}
    for name, status in jobs:
        key = "sync" if name.startswith("sync-") else name
        if len(latest.setdefault(key, [])) < 2:
            latest[key].append(status)
    for name, statuses in latest.items():
        if len(statuses) == 2 and all(status in ("failed", "uncertain") for status in statuses):
            label = {"sync": "Garmin sync", "morning": "Morning call", "daily_backup": "Daily backup",
                     "day_review": "Day review", "weekly_review": "Weekly review"}.get(name)
            if label:
                fix = ("Check your Garmin login or run python -m utils.garmin_sync_cli." if name == "sync"
                       else "Check the worker log and restart python -m worker.")
                problems.append(HealthProblem(f"failed-{name}", f"{label} failed twice. {fix}"))
    pref = preferences(database, user_id)
    if pref["morning_enabled"] and local.strftime("%H:%M") >= pref["morning_latest"] and (
            morning is None or morning[0] != "sent"):
        problems.append(HealthProblem("morning-missed", "Morning call was not sent by " +
                                      pref["morning_latest"] + ". Check Telegram settings and the worker log."))
    return tuple(problems)


def web_status(database: Path, user_id: int, now: datetime, timezone: str) -> str | None:
    """One short status line for the rail and Today, using the same diagnostics."""
    issues = health_problems(database, user_id, now, timezone)
    failed_sync = next((issue for issue in issues if issue.code == "failed-sync"), None)
    if failed_sync:
        return "Sync failed twice. Check your Garmin login."
    last = worker_last_seen(database)
    if last is None:
        with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
            row = db.execute("SELECT MAX(finished_at) FROM job_runs WHERE user_id=?", (user_id,)).fetchone()
        last = _timestamp(row[0] if row else None)
    if not worker_running(database) or last is None or now.astimezone(UTC) - last > HEARTBEAT_MAX_AGE:
        when = (f" since {last.astimezone(ZoneInfo(timezone)):%a} "
                f"{last.astimezone(ZoneInfo(timezone)).day} "
                f"{last.astimezone(ZoneInfo(timezone)):%b %H:%M}" if last else "")
        return "Worker not running" + when + ". Scheduled messages will not be sent."
    stale = next((issue for issue in issues if issue.code == "sync-stale"), None)
    if stale:
        return stale.text
    missed = next((issue for issue in issues if issue.code == "morning-missed"), None)
    if missed:
        return "Morning call missed. Check Telegram settings and the worker log."
    failed = next((issue for issue in issues if issue.code.startswith("failed-")), None)
    return failed.text if failed else None
