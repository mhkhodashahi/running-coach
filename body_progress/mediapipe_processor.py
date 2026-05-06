"""MediaPipe Pose adapter for body progress scans."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from body_progress.domain import BodyScanCreate, BodyScanProcessingResult
from body_progress.pose_metrics import (
    average_visibility,
    joint_angle_degrees,
    midpoint,
    normalized_distance,
    tilt_degrees,
    torso_lean_degrees,
)
from body_progress.processor import BodyScanProcessor


class MediaPipePoseProcessor(BodyScanProcessor):
    """Extract lightweight pose landmarks and posture metrics from one image."""

    def process(self, scan: BodyScanCreate) -> BodyScanProcessingResult:
        try:
            import cv2
            import mediapipe as mp
        except ImportError as exc:
            return BodyScanProcessingResult(
                status="failed",
                preview_image_path=str(scan.source_image_path),
                measurements_json={
                    "processor": "mediapipe_pose",
                    "setup": "Install MediaPipe with `python -m pip install mediapipe`.",
                },
                processor_name="mediapipe_pose",
                error_message=f"MediaPipe dependency is missing: {exc}",
            )

        image = cv2.imread(str(scan.source_image_path))
        if image is None:
            return BodyScanProcessingResult(
                status="failed",
                processor_name="mediapipe_pose",
                error_message=f"Could not read image: {scan.source_image_path}",
            )

        rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        pose_module = mp.solutions.pose
        with pose_module.Pose(static_image_mode=True, model_complexity=2, enable_segmentation=False) as pose:
            results = pose.process(rgb_image)

        if not results.pose_landmarks:
            return BodyScanProcessingResult(
                status="failed",
                preview_image_path=str(scan.source_image_path),
                measurements_json={
                    "processor": "mediapipe_pose",
                    "message": "No full-body pose landmarks were detected. Use a clear full-body photo.",
                    "view": scan.view,
                },
                processor_name="mediapipe_pose",
                error_message="No pose landmarks detected.",
            )

        landmarks = self._landmarks_to_json(pose_module, results.pose_landmarks.landmark)
        pose_quality, visible_count = average_visibility(landmarks)
        measurements = self._measurements(landmarks, pose_quality, visible_count, scan.view)
        preview_path = self._write_preview(scan.source_image_path, image, results.pose_landmarks, mp)

        return BodyScanProcessingResult(
            status="processed",
            preview_image_path=str(preview_path),
            keypoints_json={"landmarks": landmarks},
            measurements_json=measurements,
            pose_quality=pose_quality,
            processor_name="mediapipe_pose",
        )

    def _landmarks_to_json(self, pose_module: Any, landmarks: Any) -> list[dict[str, Any]]:
        names = [landmark.name.lower() for landmark in pose_module.PoseLandmark]
        return [
            {
                "name": names[index] if index < len(names) else f"landmark_{index}",
                "x": round(float(point.x), 6),
                "y": round(float(point.y), 6),
                "z": round(float(point.z), 6),
                "visibility": round(float(point.visibility), 6),
            }
            for index, point in enumerate(landmarks)
        ]

    def _measurements(
        self,
        landmarks: list[dict[str, Any]],
        pose_quality: float,
        visible_count: int,
        view: str,
    ) -> dict[str, Any]:
        points = {point["name"]: point for point in landmarks}
        measurements: dict[str, Any] = {
            "processor": "mediapipe_pose",
            "view": view,
            "pose_quality": pose_quality,
            "landmark_count": len(landmarks),
            "visible_landmark_count": visible_count,
        }

        required = {
            "left_shoulder",
            "right_shoulder",
            "left_hip",
            "right_hip",
            "left_knee",
            "right_knee",
            "left_ankle",
            "right_ankle",
        }
        if not required.issubset(points):
            measurements["message"] = "Pose landmarks were detected, but not enough body points were visible for metrics."
            return measurements

        shoulder_midpoint = midpoint(points["left_shoulder"], points["right_shoulder"])
        hip_midpoint = midpoint(points["left_hip"], points["right_hip"])
        measurements.update(
            {
                "shoulder_tilt_degrees": tilt_degrees(points["left_shoulder"], points["right_shoulder"]),
                "hip_tilt_degrees": tilt_degrees(points["left_hip"], points["right_hip"]),
                "shoulder_width_normalized": normalized_distance(points["left_shoulder"], points["right_shoulder"]),
                "hip_width_normalized": normalized_distance(points["left_hip"], points["right_hip"]),
                "torso_lean_degrees": torso_lean_degrees(shoulder_midpoint, hip_midpoint),
                "left_knee_angle_degrees": joint_angle_degrees(
                    points["left_hip"], points["left_knee"], points["left_ankle"]
                ),
                "right_knee_angle_degrees": joint_angle_degrees(
                    points["right_hip"], points["right_knee"], points["right_ankle"]
                ),
            }
        )
        measurements["symmetry_notes"] = self._symmetry_notes(measurements)
        return measurements

    def _symmetry_notes(self, measurements: dict[str, Any]) -> list[str]:
        notes: list[str] = []
        if abs(float(measurements.get("shoulder_tilt_degrees", 0.0))) > 6:
            notes.append("Shoulder line is visibly tilted in this scan.")
        if abs(float(measurements.get("hip_tilt_degrees", 0.0))) > 6:
            notes.append("Hip line is visibly tilted in this scan.")
        left_knee = float(measurements.get("left_knee_angle_degrees", 0.0))
        right_knee = float(measurements.get("right_knee_angle_degrees", 0.0))
        if abs(left_knee - right_knee) > 12:
            notes.append("Left and right knee angles differ noticeably.")
        if not notes:
            notes.append("No large left-right asymmetry was detected in the visible landmarks.")
        return notes

    def _write_preview(self, source_path: Path, image: Any, pose_landmarks: Any, mp: Any) -> Path:
        drawing = mp.solutions.drawing_utils
        styles = mp.solutions.drawing_styles
        pose_module = mp.solutions.pose
        annotated = image.copy()
        drawing.draw_landmarks(
            annotated,
            pose_landmarks,
            pose_module.POSE_CONNECTIONS,
            landmark_drawing_spec=styles.get_default_pose_landmarks_style(),
        )
        preview_path = source_path.with_name(f"{source_path.stem}_pose_preview.jpg")
        import cv2

        cv2.imwrite(str(preview_path), annotated)
        return preview_path
