"""SAM 3D Body adapter for body progress scans."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from body_progress.domain import BodyScanCreate, BodyScanProcessingResult
from body_progress.mesh_analysis import analyze_sam3d_mesh
from body_progress.processor import BodyScanProcessor


class SAM3DBodyProcessor(BodyScanProcessor):
    """Run Meta SAM 3D Body demo as an external processor."""

    def __init__(
        self,
        *,
        repo_dir: Path,
        checkpoint_path: Path,
        mhr_path: Path,
        output_dir: Path,
        python_executable: str | None = None,
        timeout_seconds: int = 900,
    ) -> None:
        self.repo_dir = repo_dir
        self.checkpoint_path = checkpoint_path
        self.mhr_path = mhr_path
        self.output_dir = output_dir
        self.python_executable = python_executable or sys.executable
        self.timeout_seconds = timeout_seconds

    def process(self, scan: BodyScanCreate) -> BodyScanProcessingResult:
        missing = self._missing_paths()
        if missing:
            return BodyScanProcessingResult(
                status="failed",
                preview_image_path=str(scan.source_image_path),
                measurements_json={
                    "processor": "sam3d_body",
                    "missing_paths": missing,
                    "setup": "Download the approved Hugging Face checkpoint files before using SAM 3D Body.",
                },
                processor_name="sam3d_body",
                error_message=f"SAM 3D Body is not ready. Missing: {', '.join(missing)}",
            )

        scan_output_dir = self.output_dir / f"user_{scan.user_id}" / scan.scan_date.isoformat() / scan.source_image_path.stem
        input_dir = scan_output_dir / "input"
        render_dir = scan_output_dir / "sam3d"
        input_dir.mkdir(parents=True, exist_ok=True)
        render_dir.mkdir(parents=True, exist_ok=True)

        input_image = input_dir / scan.source_image_path.name
        if scan.source_image_path.resolve() != input_image.resolve():
            shutil.copy2(scan.source_image_path, input_image)

        command = [
            self.python_executable,
            "-m",
            "body_progress.sam3d_cli",
            "--repo_dir",
            str(self.repo_dir),
            "--image_path",
            str(input_image),
            "--output_dir",
            str(render_dir),
            "--checkpoint_path",
            str(self.checkpoint_path),
            "--mhr_path",
            str(self.mhr_path),
        ]
        env = os.environ.copy()
        env.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
        env["SAM3D_MHR_PATH"] = str(self.mhr_path)
        project_root = Path(__file__).resolve().parents[1]
        env["PYTHONPATH"] = os.pathsep.join(
            [str(project_root), str(self.repo_dir), env.get("PYTHONPATH", "")]
        )

        try:
            completed = subprocess.run(
                command,
                cwd=project_root,
                env=env,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            return BodyScanProcessingResult(
                status="failed",
                preview_image_path=str(scan.source_image_path),
                measurements_json={
                    "processor": "sam3d_body",
                    "timeout_seconds": self.timeout_seconds,
                    "message": "SAM 3D Body timed out before producing scan metrics.",
                },
                processor_name="sam3d_body",
                error_message=f"SAM 3D Body timed out after {self.timeout_seconds} seconds: {exc}",
            )

        output_payload = self._parse_stdout(completed.stdout)
        preview_path = Path(output_payload["preview_path"]) if output_payload.get("preview_path") else self._find_preview(render_dir, input_image)
        mesh_paths = [str(path) for path in output_payload.get("mesh_paths", [])]
        measurements = {
            "processor": "sam3d_body",
            "return_code": completed.returncode,
            "sam3d_mesh_count": len(mesh_paths),
            "sam3d_preview_available": preview_path is not None,
            "message": "SAM 3D Body rendered a 3D body preview." if preview_path else "SAM 3D Body did not produce a preview image.",
        }
        if mesh_paths:
            measurements["shape_metrics"] = analyze_sam3d_mesh(mesh_paths[0], output_payload.get("metadata_path"))
        if completed.returncode != 0 or preview_path is None:
            return BodyScanProcessingResult(
                status="failed",
                preview_image_path=str(scan.source_image_path),
                measurements_json=measurements,
                processor_name="sam3d_body",
                error_message=completed.stderr[-1000:] or completed.stdout[-1000:] or "SAM 3D Body failed.",
            )

        return BodyScanProcessingResult(
            status="processed",
            preview_image_path=str(preview_path),
            mesh_path=mesh_paths[0] if mesh_paths else None,
            measurements_json=measurements,
            pose_quality=None,
            processor_name="sam3d_body",
        )

    def _missing_paths(self) -> list[str]:
        required = {
            "repo_dir": self.repo_dir,
            "demo.py": self.repo_dir / "demo.py",
            "checkpoint_path": self.checkpoint_path,
            "mhr_path": self.mhr_path,
            "model_config.yaml": self.checkpoint_path.parent / "model_config.yaml",
        }
        return [name for name, path in required.items() if not path.exists()]

    def _find_preview(self, render_dir: Path, input_image: Path) -> Path | None:
        expected = render_dir / f"{input_image.stem}_sam3d_preview.jpg"
        if expected.exists():
            return expected
        previews = sorted(render_dir.glob("*.jpg"))
        return previews[0] if previews else None

    def _parse_stdout(self, stdout: str) -> dict:
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
        return {}
