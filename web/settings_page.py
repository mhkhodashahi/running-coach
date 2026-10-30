"""Settings workflows; routes only parse requests and render responses."""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime
from io import BytesIO
from typing import BinaryIO
from zoneinfo import ZoneInfo

from dotenv import set_key
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from analytics.performance import goal_time_minutes
from config import BASE_DIR, Settings, _parse_hr_zones, get_settings
from db import repository
from services.goal_service import GoalService
from services.hr_zones import heart_rate_zone_bounds
from services.import_service import GarminImportService, ImportSummary
from utils.formatting import format_goal_time
from web.formatting import short_date, sync_time
from web.view_models.me import me_view
from worker.backup import NAME as BACKUP_NAME
from worker.backup import latest_backup
from worker.state import history as worker_history
from worker.state import preferences, save_preferences, worker_running

MAX_CSV_BYTES = 10 * 1024 * 1024
_SYNC_LOCK = threading.Lock()
LOGGER = logging.getLogger(__name__)


@contextmanager
def _session(settings: Settings) -> Iterator[Session]:
    engine = create_engine(settings.db_url)
    try:
        with Session(engine) as session:
            with session.begin():
                yield session
    finally:
        engine.dispose()


def settings_context(settings: Settings, sync_state: dict[str, str]) -> dict:
    """Read profile, goals, sync status and coach usage for the Settings page."""
    with _session(settings) as session:
        user = session.get(repository.User, settings.default_user_id)
        if user is None:
            raise ValueError("Profile is not configured")
        goals = repository.list_goals(session, user.id)
        last_sync = repository.get_last_garmin_sync(session, user.id)
        usage = session.execute(repository.text(
            "SELECT COUNT(*) FROM coach_llm_calls WHERE user_id=:uid AND local_day=:day"),
            {"uid": user.id, "day": datetime.now(ZoneInfo(settings.local_timezone)).date().isoformat()},
        ).scalar_one()
        profile = {key: getattr(user, key) for key in ("name", "age", "gender", "weight", "height", "max_hr")}
        goal_rows = [{"id": goal.id, "name": goal.name, "goal_type": goal.goal_type,
                      "distance": goal.target_distance_km, "time": goal.target_time_minutes,
                      "date": goal.target_date, "time_text": format_goal_time(goal.target_time_minutes),
                      "priority": goal.priority, "notes": goal.notes,
                      "active": goal.is_active, "status": goal.status} for goal in goals]
    bounds = (settings.hr_zones or tuple((name, round(low), None if high == float("inf") else round(high) - 1)
                                          for name, low, high in heart_rate_zone_bounds(profile["max_hr"])))
    today = datetime.now(ZoneInfo(settings.local_timezone)).date()
    sync_label = sync_time(last_sync.isoformat() if last_sync else None, today, settings.local_timezone)
    goal_types = GoalService.supported_goal_types()
    known_types = {kind for kind, _, _ in goal_types}
    for goal in goal_rows:
        if goal["goal_type"] not in known_types:
            goal_types.append((goal["goal_type"], GoalService.label_for(goal["goal_type"]), goal["distance"]))
            known_types.add(goal["goal_type"])
    context = {"profile": profile, "goals": goal_rows, "goal_types": goal_types,
            "zones": bounds, "custom_zones": bool(settings.hr_zones), "sleep_goal": settings.sleep_goal_hours,
            "last_sync": sync_label, "sync_state": sync_state.copy(), "provider": settings.llm_provider,
            "model": (settings.openai_model if settings.llm_provider in ("openai", "chatgpt") else
                      settings.ollama_model if settings.llm_provider == "ollama" else "Not configured"),
            "remote_sharing": settings.allow_remote_llm and settings.remote_athlete_data_approved,
            "usage": usage, "call_limit": settings.coach_daily_call_limit,
            "sync": sync_label, "messages": preferences(settings.db_path, settings.default_user_id),
            "worker_runs": worker_history(settings.db_path, settings.default_user_id, 8),
            "worker_running": worker_running(settings.db_path)}
    backup = latest_backup(settings.backup_dir)
    backup_day = BACKUP_NAME.fullmatch(backup.name).group(2) if backup else None
    with sqlite3.connect(settings.db_path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        backup_run = (db.execute("SELECT status FROM job_runs WHERE user_id=? AND job='daily_backup' "
                                 "AND run_date=?", (settings.default_user_id, backup_day)).fetchone()
                      if backup else None)
    context["last_backup"] = (f"{short_date(backup_day)} · OK" if backup_run and
                               backup_run[0] == "done" else "No verified backup yet")
    context["backup_folder"] = str(settings.backup_dir)
    project = tomllib.loads((BASE_DIR / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    context["me"] = me_view(context, telegram_configured=bool(settings.telegram_bot_token and
                             settings.telegram_chat_id), garmin_configured=bool(settings.garmin_email and
                             settings.garmin_password), public_link_configured=bool(settings.public_url),
                             version=project["version"], source_url=project["urls"]["Repository"])
    return context


def save_messages(settings: Settings, fields: dict[str, str]) -> None:
    toggles = ("morning_enabled", "morning_llm", "day_llm", "weekly_llm")
    values = {key: int(fields.get(key) == "on") for key in toggles}
    for key in ("morning_latest", "day_review_time", "weekly_time", "quiet_start", "quiet_end"):
        values[key] = fields[key]
    values["weekly_weekday"] = int(fields["weekly_weekday"])
    save_preferences(settings.db_path, settings.default_user_id, values)


def save_profile(settings: Settings, fields: dict[str, str]) -> None:
    """Validate and save only the editable profile columns."""
    name = fields.get("name", "").strip()
    age = int(fields["age"])
    gender = fields["gender"]
    weight = float(fields["weight"])
    height = float(fields["height"])
    max_hr = int(fields["max_hr"])
    if not name or len(name) > 80 or not 16 <= age <= 100 or gender not in ("male", "female", "other", "unspecified"):
        raise ValueError("Check the name, age and sex fields")
    if not 30 <= weight <= 300 or not 100 <= height <= 250 or not 100 <= max_hr <= 240:
        raise ValueError("Check weight, height and maximum heart rate")
    with _session(settings) as session:
        repository.update_user_profile(session, settings.default_user_id,
                                       {"name": name, "age": age, "gender": gender,
                                        "weight": weight, "height": height, "max_hr": max_hr})


def save_goal(settings: Settings, fields: dict[str, str], goal_id: int | None = None) -> None:
    """Create or update a goal using existing repository operations."""
    name = fields.get("name", "").strip()
    goal_type = fields["goal_type"]
    allowed_types = {kind for kind, _, _ in GoalService.supported_goal_types()}
    if goal_id is not None:
        with _session(settings) as session:
            existing = repository.get_goal(session, goal_id)
            if existing is None or existing.user_id != settings.default_user_id:
                raise ValueError("Goal not found")
            allowed_types.add(existing.goal_type)
    if not name or len(name) > 80 or goal_type not in allowed_types:
        raise ValueError("Choose a valid goal name and type")
    distance = float(fields["target_distance_km"])
    if not 1 <= distance <= 300:
        raise ValueError("Distance must be between 1 and 300 km")
    if not re.fullmatch(r"\d{2}:[0-5]\d:[0-5]\d", fields["target_time"]):
        raise ValueError("Target time must use HH:MM:SS")
    target_time = float(goal_time_minutes(fields["target_time"]))
    if target_time <= 0:
        raise ValueError("Target time must be positive")
    target_date = date.fromisoformat(fields["target_date"]) if fields.get("target_date") else None
    priority = fields.get("priority", "A")
    if priority not in ("A", "B", "C"):
        raise ValueError("Invalid priority")
    payload = {"name": name, "goal_type": goal_type, "target_distance_km": distance,
               "target_time_minutes": target_time, "target_date": target_date,
               "priority": priority, "notes": fields.get("notes", "").strip() or None}
    with _session(settings) as session:
        if goal_id is None:
            repository.create_goal(session, settings.default_user_id,
                                   payload | {"status": "planned", "is_active": False})
        else:
            goal = repository.get_goal(session, goal_id)
            if goal is None or goal.user_id != settings.default_user_id:
                raise ValueError("Goal not found")
            repository.update_goal(session, goal_id, payload)


def change_goal_state(settings: Settings, goal_id: int, action: str) -> None:
    """Activate or archive a goal without deleting it."""
    with _session(settings) as session:
        goal = repository.get_goal(session, goal_id)
        if goal is None or goal.user_id != settings.default_user_id:
            raise ValueError("Goal not found")
        if action == "activate":
            repository.set_active_goal(session, settings.default_user_id, goal_id)
        elif action == "archive":
            goal.status = "archived"
            goal.is_active = False
            session.flush()
        else:
            raise ValueError("Unknown goal action")


def save_local_config(settings: Settings, key: str, raw: str) -> Settings:
    """Persist the two editable local settings without rewriting other .env keys."""
    if key == "HR_ZONES":
        zones = _parse_hr_zones(raw)
        if zones and (len(zones) != 5 or any(not zone[0].startswith(f"Z{index}") for index, zone in enumerate(zones, 1))):
            raise ValueError("Enter five zones named Z1 through Z5")
        if zones and any(previous[2] is None or previous[2] >= current[1]
                         for previous, current in zip(zones, zones[1:], strict=False)):
            raise ValueError("Zone bounds must increase without overlap")
        updated = replace(settings, hr_zones=zones)
    elif key == "SLEEP_GOAL_HOURS":
        goal = float(raw)
        if not 4 <= goal <= 12:
            raise ValueError("Sleep goal must be between 4 and 12 hours")
        updated = replace(settings, sleep_goal_hours=goal)
    else:
        raise ValueError("This setting cannot be edited here")
    env_path = settings.base_dir / ".env"
    env_path.touch(mode=0o600, exist_ok=True)
    set_key(str(env_path), key, raw)
    os.chmod(env_path, 0o600)
    if settings.base_dir == BASE_DIR:
        os.environ[key] = raw
        get_settings.cache_clear()
    return updated


def import_csv(settings: Settings, activities: BinaryIO | None, health: BinaryIO | None) -> ImportSummary:
    """Import bounded uploaded CSVs through the existing importer."""
    if activities is None and health is None:
        raise ValueError("Choose at least one CSV file")
    with _session(settings) as session:
        return GarminImportService().import_files(session, settings.default_user_id,
                                                   activities_source=activities, health_source=health)


def uploaded_csv(name: str | None, content: bytes) -> BytesIO | None:
    if not name:
        return None
    if not name.lower().endswith(".csv") or len(content) > MAX_CSV_BYTES:
        raise ValueError("Choose a CSV file smaller than 10 MB")
    return BytesIO(content)


def sync_now(settings: Settings, state: dict[str, str]) -> None:
    """Background job: keep progress and result without exposing credentials."""
    if not _SYNC_LOCK.acquire(blocking=False):
        state.update(status="busy", message="A Garmin sync is already running")
        return
    try:
        state.update(status="running", message="Connecting to Garmin")
        with _session(settings) as session:
            result = GarminImportService().sync_garmin(session, settings.default_user_id,
                                                        days=settings.garmin_sync_days,
                                                        health_days=settings.garmin_health_sync_days)
        state.update(status="done", message=(f"Imported {result.activities_imported} activities, "
                                             f"{result.health_rows_imported} health days, "
                                             f"{result.laps_imported} laps and {result.track_points_imported} samples"))
    except Exception:
        LOGGER.exception("Garmin sync failed")
        state.update(status="error", message="Garmin sync failed. Check the server log and credentials.")
    finally:
        _SYNC_LOCK.release()
