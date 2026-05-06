"""Body scan processor interface.

The placeholder implementation is intentionally lightweight. A SAM 3D Body
adapter can implement the same interface in a separate environment with GPU
dependencies.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from body_progress.domain import BodyScanCreate, BodyScanProcessingResult


class BodyScanProcessor(ABC):
    """Processor contract for body scan inference."""

    @abstractmethod
    def process(self, scan: BodyScanCreate) -> BodyScanProcessingResult:
        """Process one body scan and return derived artifacts."""


class PlaceholderBodyScanProcessor(BodyScanProcessor):
    """No-op processor used until SAM 3D Body is installed."""

    def process(self, scan: BodyScanCreate) -> BodyScanProcessingResult:
        return BodyScanProcessingResult(
            status="uploaded",
            preview_image_path=str(scan.source_image_path),
            measurements_json={
                "message": "SAM 3D Body processing is not configured yet.",
                "recommended_next_step": "Install a GPU-backed BodyScanProcessor adapter.",
                "view": scan.view,
            },
            pose_quality=None,
            processor_name="placeholder",
        )
