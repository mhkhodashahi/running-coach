"""Reliability checks use disposable databases, folders and a fake clock."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from config import get_settings
from db.migration_runner import upgrade_database
from scripts.restore_db import restore_database
from worker import jobs
from worker.__main__ import acquire_lock
from worker.backup import daily_backup, latest_backup, prune_backups
from worker.health import health_problems, web_status, worker_last_seen
from worker.state import claim, finish

ZONE = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 10, 28, 10, 1, tzinfo=ZONE)


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "coach.db"
    upgrade_database(path)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO users(id,name,marathon_goal_time) VALUES(1,'Invented','04:00:00')")
        db.execute("INSERT INTO garmin_sync_status(user_id,last_synced_at) VALUES(1,?)",
                   ((NOW - timedelta(hours=2)).isoformat(),))
    return path


def _codes(database: Path, now: datetime = NOW) -> set[str]:
    return {problem.code for problem in health_problems(database, 1, now, "Europe/Berlin")}


def test_stale_garmin_alert_names_fix_without_secrets(database: Path) -> None:
    with sqlite3.connect(database) as db:
        db.execute("UPDATE garmin_sync_status SET last_synced_at=? WHERE user_id=1",
                   ((NOW - timedelta(hours=27)).isoformat(),))
    problems = health_problems(database, 1, NOW, "Europe/Berlin")
    assert "sync-stale" in {problem.code for problem in problems}
    assert "python -m utils.garmin_sync_cli" in problems[0].text
    assert "password" not in problems[0].text.lower()
    assert "sync-stale" not in _codes(database, NOW - timedelta(hours=1, minutes=1))


def test_two_consecutive_job_failures_and_success_resets(database: Path) -> None:
    for index, day in enumerate((date(2026, 10, 27), date(2026, 10, 28))):
        when = NOW - timedelta(days=1 - index)
        assert claim(database, 1, "sync-06", day, when)
        finish(database, 1, "sync-06", day, when, error="redacted")
    assert "failed-sync" in _codes(database)
    assert "Sync failed twice" in web_status(database, 1, NOW, "Europe/Berlin")
    next_day = date(2026, 10, 29)
    assert claim(database, 1, "sync-06", next_day, NOW + timedelta(days=1))
    finish(database, 1, "sync-06", next_day, NOW + timedelta(days=1))
    assert "failed-sync" not in _codes(database, NOW + timedelta(days=1))


def test_morning_missed_only_after_latest_time(database: Path) -> None:
    assert "morning-missed" not in _codes(database, NOW.replace(hour=9, minute=59))
    assert "morning-missed" in _codes(database)
    assert claim(database, 1, "morning", NOW.date(), NOW)
    finish(database, 1, "morning", NOW.date(), NOW, message="Morning")
    assert "morning-missed" not in _codes(database)


def test_alert_claim_is_once_per_problem_per_day(database: Path) -> None:
    job = "health-alert-sync-stale"
    assert claim(database, 1, job, NOW.date(), NOW)
    finish(database, 1, job, NOW.date(), NOW, message="Sync stale")
    assert not claim(database, 1, job, NOW.date(), NOW + timedelta(minutes=1))
    assert claim(database, 1, job, NOW.date() + timedelta(days=1), NOW + timedelta(days=1))


def test_worker_heartbeat_uses_lock_mtime(database: Path) -> None:
    lock_path = database.with_suffix(".worker.lock")
    handle = acquire_lock(lock_path)
    try:
        os.utime(lock_path, (NOW.timestamp(), NOW.timestamp()))
        assert worker_last_seen(database) == NOW.astimezone(ZoneInfo("UTC"))
    finally:
        handle.close()
    assert "Worker not running" in web_status(database, 1, NOW, "Europe/Berlin")


def test_web_status_uses_last_job_time_without_heartbeat(database: Path) -> None:
    assert claim(database, 1, "sync-06", NOW.date(), NOW - timedelta(hours=1))
    finish(database, 1, "sync-06", NOW.date(), NOW - timedelta(hours=1))
    assert "since Wed 28 Oct 09:01" in web_status(database, 1, NOW, "Europe/Berlin")


def test_daily_backup_integrity_and_sunday_copy(database: Path, tmp_path: Path) -> None:
    folder = tmp_path / "backups"
    sunday = date(2026, 10, 25)
    path = daily_backup(database, folder, sunday, Path(__file__).resolve().parents[1])
    assert path.name == "pulse.daily.2026-10-25.db"
    assert (folder / "pulse.weekly.2026-10-25.db").exists()
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("SELECT name FROM users WHERE id=1").fetchone() == ("Invented",)
    assert latest_backup(folder) == path
    assert path.stat().st_mode & 0o777 == 0o600


def test_retention_only_deletes_owned_old_files(tmp_path: Path) -> None:
    folder = tmp_path / "backups"
    folder.mkdir()
    for index in range(25):
        day = date(2026, 10, 1) + timedelta(days=index)
        (folder / f"pulse.daily.{day}.db").touch()
        if index % 2 == 0:
            (folder / f"pulse.weekly.{day}.db").touch()
    unrelated = folder / "personal.db"
    unrelated.touch()
    lookalike = folder / "pulse.daily.not-a-date.db"
    lookalike.touch()
    removed = prune_backups(folder)
    assert len(removed) == (25 - 14) + (13 - 8)
    assert unrelated.exists() and lookalike.exists()
    assert len(list(folder.glob("pulse.daily.2026-*.db"))) == 14
    assert len(list(folder.glob("pulse.weekly.2026-*.db"))) == 8


def test_restore_requires_confirmation_and_refuses_worker_lock(database: Path, tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    with sqlite3.connect(database) as original, sqlite3.connect(source) as target:
        original.backup(target)
    with pytest.raises(ValueError, match="confirmation"):
        restore_database(source, database, tmp_path / "backups", confirmed=False)
    lock = acquire_lock(database.with_suffix(".worker.lock"))
    try:
        with pytest.raises(RuntimeError, match="Stop the worker"):
            restore_database(source, database, tmp_path / "backups", confirmed=True)
    finally:
        lock.close()
    with sqlite3.connect(database) as db:
        db.execute("UPDATE users SET name='Changed' WHERE id=1")
    safety = restore_database(source, database, tmp_path / "backups", confirmed=True)
    with sqlite3.connect(database) as db, sqlite3.connect(safety) as old:
        assert db.execute("SELECT name FROM users WHERE id=1").fetchone() == ("Invented",)
        assert old.execute("SELECT name FROM users WHERE id=1").fetchone() == ("Changed",)


def test_tick_backs_up_after_morning_sync_and_alerts_once(database: Path, tmp_path: Path,
                                                         monkeypatch) -> None:
    settings = replace(get_settings(), db_path=database, default_user_id=1,
                       backup_dir=tmp_path / "pulse-backups", llm_provider="none")

    class FakeTelegram:
        configured = True

        def __init__(self):
            self.messages: list[str] = []

        def send_text(self, message: str) -> None:
            self.messages.append(message)

        def send_message(self, html: str, keyboard=(), plain=None) -> str:
            self.messages.append(html)
            return "html"

        def redact(self, message: str) -> str:
            return message

    fake = FakeTelegram()
    monkeypatch.setattr(jobs, "dispatch_effort_prompts", lambda *_args: 0)
    monkeypatch.setattr(jobs, "health_ready", lambda *_args: False)
    morning_time = NOW.replace(hour=7, minute=10)
    jobs.tick(settings, morning_time, fake, sync_job=lambda: None)
    jobs.tick(settings, morning_time + timedelta(minutes=1), fake, sync_job=lambda: None)
    assert (settings.backup_dir / "pulse.daily.2026-10-28.db").exists()
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT status FROM job_runs WHERE job='daily_backup'").fetchone() == ("done",)
        db.execute("UPDATE garmin_sync_status SET last_synced_at=? WHERE user_id=1",
                   ((NOW - timedelta(hours=27)).isoformat(),))
    monkeypatch.setattr(jobs, "morning_payload", lambda *_args, **_kwargs: "Morning call")
    jobs.tick(settings, NOW, fake, sync_job=lambda: None)
    jobs.tick(settings, NOW + timedelta(minutes=1), fake, sync_job=lambda: None)
    assert len([message for message in fake.messages if "Garmin sync has not worked" in message]) == 1
    assert all("secret" not in message.lower() for message in fake.messages)
