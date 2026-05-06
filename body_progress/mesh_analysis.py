"""Shape and proportion metrics extracted from SAM 3D Body mesh outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import trimesh


def _round(value: float | int | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    if not np.isfinite(float(value)):
        return None
    return round(float(value), digits)


def _load_metadata(metadata_path: str | None) -> dict[str, Any]:
    if not metadata_path:
        return {}
    path = Path(metadata_path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _keypoint_metrics(metadata: dict[str, Any]) -> dict[str, Any]:
    outputs = metadata.get("outputs") or []
    if not outputs:
        return {}
    keypoints = np.asarray(outputs[0].get("pred_keypoints_2d") or [], dtype=float)
    if keypoints.ndim != 2 or keypoints.shape[0] < 13 or keypoints.shape[1] < 2:
        return {}

    left_shoulder, right_shoulder = keypoints[5, :2], keypoints[6, :2]
    left_hip, right_hip = keypoints[11, :2], keypoints[12, :2]
    shoulder_width = float(np.linalg.norm(left_shoulder - right_shoulder))
    hip_width = float(np.linalg.norm(left_hip - right_hip))
    shoulder_midpoint = (left_shoulder + right_shoulder) / 2
    hip_midpoint = (left_hip + right_hip) / 2
    torso_height = float(np.linalg.norm(shoulder_midpoint - hip_midpoint))

    return {
        "sam3d_keypoint_shoulder_width_px": _round(shoulder_width, 2),
        "sam3d_keypoint_hip_width_px": _round(hip_width, 2),
        "sam3d_keypoint_shoulder_to_hip_ratio": _round(shoulder_width / hip_width if hip_width else None, 3),
        "sam3d_keypoint_torso_height_px": _round(torso_height, 2),
    }


def analyze_sam3d_mesh(mesh_path: str | Path, metadata_path: str | None = None) -> dict[str, Any]:
    """Return non-medical shape/proportion metrics from a SAM 3D Body mesh."""

    mesh_path = Path(mesh_path)
    if not mesh_path.exists():
        return {
            "sam3d_mesh_analysis_status": "missing_mesh",
        }

    mesh = trimesh.load_mesh(mesh_path, process=False)
    vertices = np.asarray(mesh.vertices, dtype=float)
    bounds = np.asarray(mesh.bounds, dtype=float)
    extents = np.asarray(mesh.extents, dtype=float)
    width_x, height_y, depth_z = [float(value) for value in extents[:3]]
    center = np.asarray(mesh.centroid, dtype=float)

    upper = vertices[vertices[:, 1] >= center[1]]
    lower = vertices[vertices[:, 1] < center[1]]
    left = vertices[vertices[:, 0] < center[0]]
    right = vertices[vertices[:, 0] >= center[0]]
    front = vertices[vertices[:, 2] >= center[2]]
    back = vertices[vertices[:, 2] < center[2]]

    metadata = _load_metadata(metadata_path)
    metrics: dict[str, Any] = {
        "sam3d_mesh_analysis_status": "processed",
        "sam3d_vertex_count": int(len(vertices)),
        "sam3d_face_count": int(len(mesh.faces)) if hasattr(mesh, "faces") else None,
        "sam3d_bounds_min": [_round(value) for value in bounds[0]],
        "sam3d_bounds_max": [_round(value) for value in bounds[1]],
        "sam3d_height_proxy": _round(height_y),
        "sam3d_width_proxy": _round(width_x),
        "sam3d_depth_proxy": _round(depth_z),
        "sam3d_width_to_height_ratio": _round(width_x / height_y if height_y else None),
        "sam3d_depth_to_height_ratio": _round(depth_z / height_y if height_y else None),
        "sam3d_width_to_depth_ratio": _round(width_x / depth_z if depth_z else None),
        "sam3d_upper_body_vertex_ratio": _round(len(upper) / len(vertices) if len(vertices) else None, 3),
        "sam3d_lower_body_vertex_ratio": _round(len(lower) / len(vertices) if len(vertices) else None, 3),
        "sam3d_left_right_vertex_balance": _round(
            abs(len(left) - len(right)) / len(vertices) if len(vertices) else None,
            3,
        ),
        "sam3d_front_back_vertex_balance": _round(
            abs(len(front) - len(back)) / len(vertices) if len(vertices) else None,
            3,
        ),
        "sam3d_person_count": metadata.get("person_count"),
    }
    metrics.update(_keypoint_metrics(metadata))
    return metrics
