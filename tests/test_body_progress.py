from __future__ import annotations

from datetime import date, datetime

import cv2
import numpy as np
import trimesh
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from body_progress.avatar import build_avatar_state
from body_progress.domain import BodyScanCreate, BodyScanProcessingResult, BodyScanSummary
from body_progress.mesh_analysis import analyze_sam3d_mesh
from body_progress.pose_metrics import joint_angle_degrees, normalized_distance, tilt_degrees, torso_lean_degrees
from body_progress.processor import PlaceholderBodyScanProcessor
from body_progress.sam3d_cli import _render_mesh_preview
from body_progress.sam3d_processor import SAM3DBodyProcessor
from body_progress.storage import LocalBodyScanStorage
from db import repository
from db.models import Base
from services.body_progress_service import BodyProgressService
from services.body_scan_insight_service import BodyScanInsightService, _compact_measurements


def test_local_body_scan_storage_uses_user_and_date_directory(tmp_path) -> None:
    storage = LocalBodyScanStorage(tmp_path)

    stored = storage.save_upload(
        user_id=7,
        scan_date=date(2026, 4, 30),
        filename="front.png",
        content=b"fake-image",
        content_type="image/png",
    )

    assert stored.path.exists()
    assert "user_7" in str(stored.path)
    assert "2026-04-30" in str(stored.path)
    assert stored.sha256


def test_avatar_state_reflects_readiness_and_latest_scan_date() -> None:
    scans = [
        BodyScanSummary(
            id=1,
            user_id=1,
            scan_date=date(2026, 4, 20),
            view="front",
            status="uploaded",
            source_image_path=None,
            preview_image_path=None,
            mesh_path=None,
            pose_quality=None,
            notes=None,
            created_at=datetime(2026, 4, 20, 8, 0),
        )
    ]

    avatar = build_avatar_state(
        {
            "readiness": {"score": 82},
            "fatigue": {"level": "low"},
            "weekly_mileage": {"7d": 46.2},
            "recovery": {"sleep_score": 78, "body_battery": 70},
        },
        scans,
    )

    assert avatar.title == "Ready Runner"
    assert avatar.latest_scan_date == date(2026, 4, 20)
    assert avatar.body_scan_count == 1


def test_body_progress_service_creates_scan_and_deletes_image_without_consent(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'insights.db'}", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)
    service = BodyProgressService(
        storage=LocalBodyScanStorage(tmp_path),
        processor=PlaceholderBodyScanProcessor(),
    )

    class Upload:
        def read(self) -> bytes:
            return b"private-image"

    with session_factory() as session:
        repository.get_or_create_default_user(session, 1)
        result = service.upload_scan(
            session=session,
            user_id=1,
            scan_date=date(2026, 4, 30),
            view="front",
            upload=Upload(),
            filename="front.jpg",
            content_type="image/jpeg",
            notes="baseline",
            consent_to_store_image=False,
        )
        scans = repository.list_body_scans(session, 1)

    assert result.status == "uploaded"
    assert scans[0].source_image_path is None
    assert scans[0].preview_image_path is None
    assert not any(tmp_path.rglob("*.jpg"))


def test_pose_metric_helpers_return_stable_values() -> None:
    left = {"x": 0.25, "y": 0.40}
    right = {"x": 0.75, "y": 0.40}
    hip = {"x": 0.50, "y": 0.70}
    knee = {"x": 0.50, "y": 0.85}
    ankle = {"x": 0.50, "y": 1.0}

    assert tilt_degrees(left, right) == 0
    assert normalized_distance(left, right) == 0.5
    assert torso_lean_degrees({"x": 0.50, "y": 0.40}, hip) == 0
    assert joint_angle_degrees(hip, knee, ankle) == 180


def test_sam3d_processor_reports_missing_checkpoint(tmp_path) -> None:
    source = tmp_path / "front.jpg"
    source.write_bytes(b"not-an-image")
    processor = SAM3DBodyProcessor(
        repo_dir=tmp_path / "missing-repo",
        checkpoint_path=tmp_path / "missing.ckpt",
        mhr_path=tmp_path / "missing-mhr.pt",
        output_dir=tmp_path / "out",
    )

    result = processor.process(
        BodyScanCreate(
            user_id=1,
            scan_date=date(2026, 5, 1),
            view="front",
            source_image_path=source,
        )
    )

    assert result.status == "failed"
    assert result.processor_name == "sam3d_body"
    assert result.measurements_json is not None
    assert "checkpoint_path" in result.measurements_json["missing_paths"]


def test_analyze_sam3d_mesh_extracts_shape_metrics(tmp_path) -> None:
    mesh_path = tmp_path / "body.ply"
    mesh = trimesh.Trimesh(
        vertices=np.array(
            [
                [-1, 0, -0.5],
                [1, 0, -0.5],
                [-1, 2, -0.5],
                [1, 2, -0.5],
                [-1, 0, 0.5],
                [1, 0, 0.5],
                [-1, 2, 0.5],
                [1, 2, 0.5],
            ]
        ),
        faces=np.array([[0, 1, 2], [1, 3, 2], [4, 6, 5], [5, 6, 7]]),
        process=False,
    )
    mesh.export(mesh_path)

    metrics = analyze_sam3d_mesh(mesh_path)

    assert metrics["sam3d_mesh_analysis_status"] == "processed"
    assert metrics["sam3d_height_proxy"] == 2
    assert metrics["sam3d_width_proxy"] == 2
    assert metrics["sam3d_depth_proxy"] == 1
    assert metrics["sam3d_width_to_height_ratio"] == 1
    assert "sam3d_mesh_path" not in metrics


def test_sam3d_mesh_preview_renders_image(tmp_path) -> None:
    mesh_path = tmp_path / "body.ply"
    preview_path = tmp_path / "body_preview.jpg"
    mesh = trimesh.creation.box(extents=(0.5, 1.8, 0.3))
    mesh.export(mesh_path)

    _render_mesh_preview(mesh_path, preview_path, width=320, height=420)

    assert preview_path.exists()
    image = cv2.imread(str(preview_path))
    assert image is not None
    assert image.shape[:2] == (420, 320)
    assert np.count_nonzero(image < 245) > 1000


def test_body_scan_insight_service_stores_history_for_next_call(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'insights.db'}", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)

    class FakeLLM:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        def generate_json(self, system_prompt, user_prompt, response_schema=None):
            self.prompts.append(user_prompt)
            return {
                "summary": f"Insight call {len(self.prompts)}",
                "visual_changes": ["Latest scan is usable for comparison."],
                "posture_and_symmetry": ["Shoulder tilt is low."],
                "running_form_implications": ["Use this as a cue, not a diagnosis."],
                "progress_trends": ["Need repeated matching views for trend confidence."],
                "risks_or_unknowns": ["Camera angle can distort posture metrics."],
                "coaching_actions": ["Keep strength work consistent."],
                "next_photo_protocol": ["Use the same camera height next time."],
                "evidence": ["Pose quality 0.91."],
                "limitations": ["Photo metrics are not medical diagnosis."],
                "confidence": 72,
            }

    fake_llm = FakeLLM()
    service = BodyScanInsightService(llm_client=fake_llm)

    with session_factory() as session:
        user = repository.get_or_create_default_user(session, 1)
        scan = repository.create_body_scan(
            session,
            BodyScanCreate(
                user_id=user.id,
                scan_date=date(2026, 4, 30),
                view="front",
                source_image_path=tmp_path / "front.jpg",
            ),
        )
        repository.update_body_scan_result(
            session,
            scan.id,
            BodyScanProcessingResult(
                status="processed",
                measurements_json={"pose_quality": 0.91, "shoulder_tilt_degrees": 2.1},
                pose_quality=0.91,
                processor_name="mediapipe_pose",
            ),
        )
        session.commit()

        first = service.generate(session, user, athlete_question="What changed?")
        session.commit()
        second = service.generate(session, user, athlete_question="Use history.")
        session.commit()
        insights = repository.body_scan_insights_dataframe(session, user.id)

    assert first.payload["summary"] == "Insight call 1"
    assert second.payload["summary"] == "Insight call 2"
    assert len(insights) == 2
    assert "Insight call 1" in fake_llm.prompts[1]


def test_body_scan_insight_service_keeps_unstructured_llm_text(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'unstructured.db'}", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)

    class FakeLLM:
        def generate_json(self, system_prompt, user_prompt, response_schema=None):
            return {"explanation": "Your latest scan shows usable posture data but needs consistent side-view repeats."}

    service = BodyScanInsightService(llm_client=FakeLLM())

    with session_factory() as session:
        user = repository.get_or_create_default_user(session, 1)
        scan = repository.create_body_scan(
            session,
            BodyScanCreate(
                user_id=user.id,
                scan_date=date(2026, 4, 30),
                view="side",
                source_image_path=tmp_path / "side.jpg",
            ),
        )
        repository.update_body_scan_result(
            session,
            scan.id,
            BodyScanProcessingResult(
                status="processed",
                measurements_json={"pose_quality": 0.8, "torso_lean_degrees": 4.5},
                pose_quality=0.8,
                processor_name="mediapipe_pose",
            ),
        )
        session.commit()

        result = service.generate(session, user)

    assert result.payload["summary"].startswith("Your latest scan shows")
    assert result.payload["llm_warning"] == "LLM returned prose instead of the requested full JSON schema."


def test_body_scan_llm_context_removes_runtime_measurement_fields() -> None:
    compact = _compact_measurements(
        {
            "processor": "sam3d_body",
            "checkpoint_path": "/private/model.ckpt",
            "mhr_path": "/private/mhr.pt",
            "repo_dir": "/private/repo",
            "command": ["python", "demo.py"],
            "stdout_tail": "debug",
            "stderr_tail": "debug",
            "metadata_path": "/private/metadata.json",
            "shape_metrics": {
                "sam3d_height_proxy": 1.7,
                "sam3d_width_to_height_ratio": 0.5,
                "sam3d_mesh_path": "/private/body.ply",
                "sam3d_bounds_min": [0, 0, 0],
            },
        }
    )

    assert compact == {
        "processor": "sam3d_body",
        "shape_metrics": {
            "sam3d_height_proxy": 1.7,
            "sam3d_width_to_height_ratio": 0.5,
        },
    }
