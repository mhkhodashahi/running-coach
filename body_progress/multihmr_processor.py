"""Multi-HMR adapter hook for future 3D mesh processing."""

from __future__ import annotations

from pathlib import Path

from body_progress.domain import BodyScanCreate, BodyScanProcessingResult
from body_progress.processor import BodyScanProcessor


class MultiHMRProcessor(BodyScanProcessor):
    """Documented adapter boundary for running Multi-HMR outside Streamlit."""

    def __init__(self, repo_dir: Path, output_dir: Path, python_executable: str = "python") -> None:
        self.repo_dir = repo_dir
        self.output_dir = output_dir
        self.python_executable = python_executable

    def process(self, scan: BodyScanCreate) -> BodyScanProcessingResult:
        if not self.repo_dir.exists():
            return BodyScanProcessingResult(
                status="failed",
                preview_image_path=str(scan.source_image_path),
                measurements_json={
                    "processor": "multihmr",
                    "setup": f"Clone Multi-HMR into {self.repo_dir} or set MULTIHMR_REPO_DIR.",
                    "recommended_default": "Use BODY_SCAN_PROCESSOR=mediapipe for immediate local pose metrics.",
                },
                processor_name="multihmr",
                error_message=f"Multi-HMR repo not found: {self.repo_dir}",
            )

        scan_output_dir = self.output_dir / f"user_{scan.user_id}" / scan.scan_date.isoformat()
        scan_output_dir.mkdir(parents=True, exist_ok=True)
        return BodyScanProcessingResult(
            status="uploaded",
            preview_image_path=str(scan.source_image_path),
            measurements_json={
                "processor": "multihmr",
                "repo_dir": str(self.repo_dir),
                "output_dir": str(scan_output_dir),
                "manual_command": (
                    f"{self.python_executable} demo.py --img_folder {scan.source_image_path.parent} "
                    f"--out_folder {scan_output_dir}"
                ),
                "message": "Multi-HMR is configured as an external heavy processor hook; run the command in its own environment.",
            },
            processor_name="multihmr",
        )
