"""Application configuration."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _resolve_path(raw_path: str, fallback: Path) -> Path:
    path = Path(raw_path) if raw_path else fallback
    return path if path.is_absolute() else (BASE_DIR / path).resolve()


def _resolve_db_path(raw_path: str, fallback: Path) -> Path:
    path = Path(raw_path) if raw_path else fallback
    if path.name == "marathon_coach.db":
        path = path.with_name("running_coach.db")
    return path if path.is_absolute() else (BASE_DIR / path).resolve()


@dataclass(frozen=True)
class Settings:
    """Typed application settings loaded from environment variables."""

    base_dir: Path
    data_dir: Path
    db_dir: Path
    db_path: Path
    mock_activities_path: Path
    mock_health_path: Path
    llm_provider: str
    openai_api_key: str
    openai_model: str
    allow_remote_llm: bool
    remote_athlete_data_approved: bool
    ollama_base_url: str
    ollama_model: str
    default_user_id: int
    garmin_email: str
    garmin_password: str
    garmin_token_dir: Path
    garmin_sync_days: int
    garmin_health_sync_days: int
    garmin_rate_limit_cooldown_minutes: int
    google_maps_api_key: str
    google_maps_map_id: str
    telegram_bot_token: str
    telegram_chat_id: str
    sub_four_goal_minutes: float
    recovery_threshold_hours: float
    elevated_resting_hr_threshold: int
    low_sleep_score_threshold: int
    high_intensity_ratio_threshold: float
    long_run_gap_days: int
    local_timezone: str = "Europe/Berlin"
    sleep_goal_hours: float = 7.5
    hr_zones: tuple[tuple[str, int, int | None], ...] = ()
    coach_daily_call_limit: int = 20
    sync_interval_hours: int = 2
    auto_opinions: bool = False
    public_url: str = ""
    backup_dir: Path = Path.home() / "pulse-backups"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def goal_pace_min_per_km(self) -> float:
        return self.sub_four_goal_minutes / 42.195


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""

    db_dir = BASE_DIR / "db"
    data_dir = BASE_DIR / "data"
    return Settings(
        base_dir=BASE_DIR,
        data_dir=data_dir,
        db_dir=db_dir,
        db_path=_resolve_db_path(os.getenv("DB_PATH", ""), db_dir / "running_coach.db"),
        mock_activities_path=data_dir / "mock_activities.csv",
        mock_health_path=data_dir / "mock_health_metrics.csv",
        llm_provider=os.getenv("LLM_PROVIDER", "ollama").strip().lower(),
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-6-luna").strip(),
        allow_remote_llm=os.getenv("ALLOW_REMOTE_LLM", "").strip().lower() == "true",
        remote_athlete_data_approved=os.getenv("REMOTE_ATHLETE_DATA_APPROVED", "").strip().lower() == "true",
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip(),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen3:14b").strip(),
        default_user_id=int(os.getenv("DEFAULT_USER_ID", "1")),
        garmin_email=os.getenv("GARMIN_EMAIL", "").strip(),
        garmin_password=os.getenv("GARMIN_PASSWORD", "").strip(),
        garmin_token_dir=_resolve_path(os.getenv("GARMIN_TOKEN_DIR", ".garmin_tokens"), BASE_DIR / ".garmin_tokens"),
        garmin_sync_days=int(os.getenv("GARMIN_SYNC_DAYS", "90")),
        garmin_health_sync_days=int(os.getenv("GARMIN_HEALTH_SYNC_DAYS", "21")),
        garmin_rate_limit_cooldown_minutes=int(os.getenv("GARMIN_RATE_LIMIT_COOLDOWN_MINUTES", "30")),
        google_maps_api_key=os.getenv("GOOGLE_MAPS_API_KEY", "").strip(),
        google_maps_map_id=os.getenv("GOOGLE_MAPS_MAP_ID", "").strip(),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
        sub_four_goal_minutes=240.0,
        recovery_threshold_hours=float(os.getenv("RECOVERY_THRESHOLD_HOURS", "36")),
        elevated_resting_hr_threshold=int(os.getenv("ELEVATED_RESTING_HR_THRESHOLD", "5")),
        low_sleep_score_threshold=int(os.getenv("LOW_SLEEP_SCORE_THRESHOLD", "72")),
        high_intensity_ratio_threshold=float(os.getenv("HIGH_INTENSITY_RATIO_THRESHOLD", "0.22")),
        long_run_gap_days=int(os.getenv("LONG_RUN_GAP_DAYS", "14")),
        local_timezone=os.getenv("LOCAL_TIMEZONE", "Europe/Berlin"),
        sleep_goal_hours=float(os.getenv("SLEEP_GOAL_HOURS", "7.5")),
        hr_zones=_parse_hr_zones(os.getenv("HR_ZONES", "")),
        coach_daily_call_limit=_coach_call_limit(os.getenv("COACH_DAILY_CALL_LIMIT", "")),
        sync_interval_hours=max(1, int(os.getenv("SYNC_INTERVAL_HOURS", "2"))),
        auto_opinions=os.getenv("AUTO_OPINIONS", "").lower() == "true",
        public_url=os.getenv("PUBLIC_URL", "").strip().rstrip("/"),
        backup_dir=Path(os.getenv("BACKUP_DIR", "").strip() or str(Path.home() / "pulse-backups")).expanduser(),
    )


def _coach_call_limit(raw: str) -> int:
    if not raw.strip():
        return 20
    limit = int(raw)
    if limit < 1:
        raise ValueError("COACH_DAILY_CALL_LIMIT must be a positive integer")
    return limit


def _parse_hr_zones(raw: str) -> tuple[tuple[str, int, int | None], ...]:
    if not raw.strip():
        return ()
    try:
        entries = json.loads(raw)
        if not isinstance(entries, list):
            raise ValueError("HR_ZONES must be a JSON array")
        zones = []
        for entry in entries:
            name, lower, upper = entry["name"], entry["lower_bpm"], entry["upper_bpm"]
            if not isinstance(name, str) or not name.strip() or type(lower) is not int or lower < 0:
                raise ValueError("Invalid HR_ZONES name or lower_bpm")
            if upper is not None and (type(upper) is not int or upper < lower):
                raise ValueError("Invalid HR_ZONES upper_bpm")
            zones.append((name, lower, upper))
        return tuple(zones)
    except (TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("HR_ZONES must be a JSON array of name, lower_bpm and upper_bpm") from exc
