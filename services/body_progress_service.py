"""Application service for body progress timeline uploads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import BinaryIO

from body_progress.domain import BodyScanCreate, BodyScanProcessingResult, BodyScanSummary
from body_progress.mediapipe_processor import MediaPipePoseProcessor
from body_progress.multihmr_processor import MultiHMRProcessor
from body_progress.processor import BodyScanProcessor, PlaceholderBodyScanProcessor
from body_progress.sam3d_processor import SAM3DBodyProcessor
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
        return repository.list_body_scans(session, user_id)

    def _create_body_scan(self, session, payload: BodyScanCreate) -> int:
        return int(repository.create_body_scan(session, payload).id)

    def _update_body_scan_result(self, session, scan_id: int, result: BodyScanProcessingResult) -> None:
        repository.update_body_scan_result(session, scan_id, result)
