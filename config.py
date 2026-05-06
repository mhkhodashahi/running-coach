"""Application configuration."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _resolve_path(raw_path: str, fallback: Path) -> Path:
    path = Path(raw_path) if raw_path else fallback
    return path if path.is_absolute() else (BASE_DIR / path).resolve()


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Typed application settings loaded from environment variables."""

    base_dir: Path
    data_dir: Path
    db_dir: Path
    db_path: Path
    mock_activities_path: Path
    mock_health_path: Path
    body_scan_dir: Path
    use_sam: bool
    body_scan_processor: str
    sam3d_repo_dir: Path
    sam3d_checkpoint_path: Path
    sam3d_mhr_path: Path
    sam3d_output_dir: Path
    sam3d_python_executable: str
    sam3d_timeout_seconds: int
    multihmr_repo_dir: Path
    multihmr_output_dir: Path
    llm_provider: str
    openai_api_key: str
    openai_model: str
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
        db_path=_resolve_path(os.getenv("DB_PATH", ""), db_dir / "marathon_coach.db"),
        mock_activities_path=data_dir / "mock_activities.csv",
        mock_health_path=data_dir / "mock_health_metrics.csv",
        body_scan_dir=_resolve_path(os.getenv("BODY_SCAN_DIR", "data/body_scans"), data_dir / "body_scans"),
        use_sam=_env_bool("USE_SAM", _env_bool("use_sam")),
        body_scan_processor=os.getenv("BODY_SCAN_PROCESSOR", "mediapipe").strip().lower(),
        sam3d_repo_dir=_resolve_path(os.getenv("SAM3D_REPO_DIR", "../sam/sam-3d-body"), BASE_DIR / "sam" / "sam-3d-body"),
        sam3d_checkpoint_path=_resolve_path(
            os.getenv("SAM3D_CHECKPOINT_PATH", "../sam/sam-3d-body/checkpoints/sam-3d-body-dinov3/model.ckpt"),
            BASE_DIR / "sam" / "sam-3d-body" / "checkpoints" / "sam-3d-body-dinov3" / "model.ckpt",
        ),
        sam3d_mhr_path=_resolve_path(
            os.getenv("SAM3D_MHR_PATH", "../sam/sam-3d-body/checkpoints/sam-3d-body-dinov3/assets/mhr_model.pt"),
            BASE_DIR / "sam" / "sam-3d-body" / "checkpoints" / "sam-3d-body-dinov3" / "assets" / "mhr_model.pt",
        ),
        sam3d_output_dir=_resolve_path(os.getenv("SAM3D_OUTPUT_DIR", "data/body_scan_outputs/sam3d"), data_dir / "body_scan_outputs" / "sam3d"),
        sam3d_python_executable=os.getenv("SAM3D_PYTHON", "").strip() or sys.executable,
        sam3d_timeout_seconds=int(os.getenv("SAM3D_TIMEOUT_SECONDS", "900")),
        multihmr_repo_dir=_resolve_path(os.getenv("MULTIHMR_REPO_DIR", "../sam/multi-hmr"), BASE_DIR / "sam" / "multi-hmr"),
        multihmr_output_dir=_resolve_path(
            os.getenv("MULTIHMR_OUTPUT_DIR", "data/body_scan_outputs"),
            data_dir / "body_scan_outputs",
        ),
        llm_provider=os.getenv("LLM_PROVIDER", "ollama").strip().lower(),
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini").strip(),
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
    )
