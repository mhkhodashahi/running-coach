"""Domain models for reusable body progress tracking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

ScanView = Literal["front", "side", "back", "running_form", "other"]
ScanStatus = Literal["uploaded", "processed", "failed"]


@dataclass(frozen=True)
class BodyScanCreate:
    """Input required to register a body progress scan."""

    user_id: int
    scan_date: date
    view: ScanView
    source_image_path: Path
    notes: str = ""
    consent_to_store_image: bool = True


@dataclass(frozen=True)
class BodyScanSummary:
    """Portable summary of one scan, independent of database implementation."""

    id: int
    user_id: int
    scan_date: date
    view: ScanView
    status: ScanStatus
    source_image_path: str | None
    preview_image_path: str | None
    mesh_path: str | None
    pose_quality: float | None
    notes: str | None
    created_at: datetime


@dataclass(frozen=True)
class AvatarState:
    """High-level avatar state that can be rendered in any UI."""

    title: str
    subtitle: str
    readiness_label: str
    load_label: str
    recovery_label: str
    color: str
    body_scan_count: int
    latest_scan_date: date | None


@dataclass(frozen=True)
class BodyScanProcessingResult:
    """Result emitted by a body scan processor."""

    status: ScanStatus
    preview_image_path: str | None = None
    mesh_path: str | None = None
    keypoints_json: dict[str, Any] | None = None
    measurements_json: dict[str, Any] | None = None
    pose_quality: float | None = None
    processor_name: str = "placeholder"
    error_message: str | None = None
