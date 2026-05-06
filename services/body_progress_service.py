"""Application service for body progress timeline uploads."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import BinaryIO

from sqlalchemy import text

from body_progress.domain import BodyScanCreate, BodyScanProcessingResult, BodyScanSummary
from body_progress.mediapipe_processor import MediaPipePoseProcessor
from body_progress.multihmr_processor import MultiHMRProcessor
from body_progress.processor import BodyScanProcessor, PlaceholderBodyScanProcessor
from body_progress.sam3d_processor import SAM3DBodyProcessor
from body_progress.sql import BODY_SCANS_CREATE_TABLE_SQL, BODY_SCANS_DATE_INDEX_SQL, BODY_SCANS_INDEX_SQL
from body_progress.storage import LocalBodyScanStorage
from config import get_settings
from db import repository


@dataclass(frozen=True)
class BodyScanUploadResult:
    """Result returned after registering a body progress scan."""

    scan_id: int
    stored_path: str
    status: str


class BodyProgressService:
    """Coordinate upload storage, processing, and persistence."""

    def __init__(
        self,
        storage: LocalBodyScanStorage | None = None,
        processor: BodyScanProcessor | None = None,
    ) -> None:
        settings = get_settings()
        self.storage = storage or LocalBodyScanStorage(settings.body_scan_dir)
        self.processor = processor or self._build_processor(settings)

    def _build_processor(self, settings) -> BodyScanProcessor:
        if settings.body_scan_processor == "mediapipe":
            return MediaPipePoseProcessor()
        if settings.body_scan_processor in {"sam3d", "sam3d_body", "sam-3d-body"}:
            return SAM3DBodyProcessor(
                repo_dir=settings.sam3d_repo_dir,
                checkpoint_path=settings.sam3d_checkpoint_path,
                mhr_path=settings.sam3d_mhr_path,
                output_dir=settings.sam3d_output_dir,
                python_executable=settings.sam3d_python_executable,
                timeout_seconds=settings.sam3d_timeout_seconds,
            )
        if settings.body_scan_processor == "multihmr":
            return MultiHMRProcessor(settings.multihmr_repo_dir, settings.multihmr_output_dir)
        return PlaceholderBodyScanProcessor()

    def upload_scan(
        self,
        *,
        session,
        user_id: int,
        scan_date: date,
        view: str,
        upload: BinaryIO,
        filename: str,
        content_type: str,
        notes: str = "",
        consent_to_store_image: bool = True,
    ) -> BodyScanUploadResult:
        stored = self.storage.save_upload(
            user_id=user_id,
            scan_date=scan_date,
            filename=filename,
            content=upload.read(),
            content_type=content_type,
        )
        create_payload = BodyScanCreate(
            user_id=user_id,
            scan_date=scan_date,
            view=view,  # type: ignore[arg-type]
            source_image_path=stored.path,
            notes=notes,
            consent_to_store_image=consent_to_store_image,
        )
        scan_id = self._create_body_scan(session, create_payload)
        result = self.processor.process(create_payload)
        if not consent_to_store_image:
            stored.path.unlink(missing_ok=True)
            result = BodyScanProcessingResult(
                status=result.status,
                preview_image_path=None,
                mesh_path=result.mesh_path,
                keypoints_json=result.keypoints_json,
                measurements_json=result.measurements_json,
                pose_quality=result.pose_quality,
                processor_name=result.processor_name,
                error_message=result.error_message,
            )
        self._update_body_scan_result(session, scan_id, result)
        return BodyScanUploadResult(
            scan_id=scan_id,
            stored_path=str(stored.path),
            status=result.status,
        )

    def list_scans(self, *, session, user_id: int) -> list[BodyScanSummary]:
        if hasattr(repository, "list_body_scans"):
            return repository.list_body_scans(session, user_id)
        rows = session.execute(
            text(
                """
                SELECT id, user_id, scan_date, view, status, source_image_path,
                       preview_image_path, mesh_path, pose_quality, notes, created_at
                FROM body_scans
                WHERE user_id = :user_id
                ORDER BY scan_date DESC, created_at DESC
                """
            ),
            {"user_id": user_id},
        ).mappings()
        return [
            BodyScanSummary(
                id=int(row["id"]),
                user_id=int(row["user_id"]),
                scan_date=row["scan_date"],
                view=row["view"],
                status=row["status"],
                source_image_path=row["source_image_path"],
                preview_image_path=row["preview_image_path"],
                mesh_path=row["mesh_path"],
                pose_quality=row["pose_quality"],
                notes=row["notes"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def _create_body_scan(self, session, payload: BodyScanCreate) -> int:
        session.execute(text(BODY_SCANS_CREATE_TABLE_SQL))
        session.execute(text(BODY_SCANS_INDEX_SQL))
        session.execute(text(BODY_SCANS_DATE_INDEX_SQL))
        if hasattr(repository, "create_body_scan"):
            return int(repository.create_body_scan(session, payload).id)

        result = session.execute(
            text(
                """
                INSERT INTO body_scans (
                    user_id, scan_date, view, status, source_image_path,
                    consent_to_store_image, notes, created_at, updated_at
                )
                VALUES (
                    :user_id, :scan_date, :view, 'uploaded', :source_image_path,
                    :consent_to_store_image, :notes, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            ),
            {
                "user_id": payload.user_id,
                "scan_date": payload.scan_date,
                "view": payload.view,
                "source_image_path": str(payload.source_image_path) if payload.consent_to_store_image else None,
                "consent_to_store_image": payload.consent_to_store_image,
                "notes": payload.notes.strip() or None,
            },
        )
        return int(result.lastrowid)

    def _update_body_scan_result(self, session, scan_id: int, result: BodyScanProcessingResult) -> None:
        if hasattr(repository, "update_body_scan_result"):
            repository.update_body_scan_result(session, scan_id, result)
            return

        session.execute(
            text(
                """
                UPDATE body_scans
                SET status = :status,
                    preview_image_path = :preview_image_path,
                    mesh_path = :mesh_path,
                    keypoints_json = :keypoints_json,
                    measurements_json = :measurements_json,
                    pose_quality = :pose_quality,
                    processor_name = :processor_name,
                    error_message = :error_message,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :scan_id
                """
            ),
            {
                "scan_id": scan_id,
                "status": result.status,
                "preview_image_path": result.preview_image_path,
                "mesh_path": result.mesh_path,
                "keypoints_json": json.dumps(result.keypoints_json) if result.keypoints_json is not None else None,
                "measurements_json": json.dumps(result.measurements_json)
                if result.measurements_json is not None
                else None,
                "pose_quality": result.pose_quality,
                "processor_name": result.processor_name,
                "error_message": result.error_message,
            },
        )
