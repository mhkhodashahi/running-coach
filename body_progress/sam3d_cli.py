"""Headless SAM 3D Body runner used by the Streamlit adapter."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import torch
import trimesh


def _jsonable(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return value


def _draw_preview(image_path: Path, outputs: list[dict], output_path: Path) -> None:
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError(f"Could not read image: {image_path}")
    for person in outputs:
        bbox = person.get("bbox")
        if bbox is not None:
            x1, y1, x2, y2 = [int(v) for v in bbox[:4]]
            cv2.rectangle(image, (x1, y1), (x2, y2), (252, 76, 2), 2)
        keypoints = person.get("pred_keypoints_2d")
        if keypoints is not None:
            for point in np.asarray(keypoints):
                if len(point) >= 2:
                    cv2.circle(image, (int(point[0]), int(point[1])), 3, (17, 24, 39), -1)
    cv2.imwrite(str(output_path), image)


def _render_mesh_preview(mesh_path: str | Path, output_path: Path, width: int = 1000, height: int = 1400) -> None:
    mesh = trimesh.load_mesh(mesh_path, process=False)
    vertices = np.asarray(mesh.vertices, dtype=float)
    faces = np.asarray(mesh.faces, dtype=np.int32)
    if vertices.size == 0 or faces.size == 0:
        raise ValueError(f"Mesh has no renderable geometry: {mesh_path}")

    center = vertices.mean(axis=0)
    vertices = vertices - center
    vertices[:, 0] = -vertices[:, 0]

    xy = vertices[:, [0, 1]]
    xy_min = xy.min(axis=0)
    xy_max = xy.max(axis=0)
    xy_span = np.maximum(xy_max - xy_min, 1e-6)
    margin = 90
    scale = min((width - margin * 2) / xy_span[0], (height - margin * 2) / xy_span[1])
    points = np.empty((len(vertices), 2), dtype=np.int32)
    points[:, 0] = ((vertices[:, 0] - xy_min[0]) * scale + margin).astype(np.int32)
    points[:, 1] = ((vertices[:, 1] - xy_min[1]) * scale + margin).astype(np.int32)

    canvas = np.full((height, width, 3), 248, dtype=np.uint8)
    face_depth = vertices[faces][:, :, 2].mean(axis=1)
    face_normals = np.asarray(mesh.face_normals, dtype=float)
    if len(face_normals) != len(faces):
        face_normals = np.zeros((len(faces), 3), dtype=float)

    depth_min = float(face_depth.min())
    depth_max = float(face_depth.max())
    depth_span = float(depth_max - depth_min) or 1.0
    for face_index in np.argsort(-face_depth):
        polygon = points[faces[face_index]]
        normal_light = max(0.0, -float(face_normals[face_index][2]))
        depth_light = (depth_max - float(face_depth[face_index])) / depth_span
        shade = int(92 + 92 * normal_light + 44 * depth_light)
        color = (max(45, shade - 68), max(65, shade - 42), min(245, shade + 16))
        cv2.fillConvexPoly(canvas, polygon, color)

    cv2.imwrite(str(output_path), canvas)


def _export_meshes(outputs: list[dict], faces: np.ndarray, output_dir: Path, stem: str) -> list[str]:
    paths: list[str] = []
    for index, person in enumerate(outputs):
        vertices = person.get("pred_vertices")
        cam_t = person.get("pred_cam_t")
        if vertices is None:
            continue
        vertices = np.asarray(vertices)
        if cam_t is not None:
            vertices = vertices + np.asarray(cam_t).reshape(1, 3)
        mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
        mesh_path = output_dir / f"{stem}_person_{index:03d}.ply"
        mesh.export(mesh_path)
        paths.append(str(mesh_path))
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Headless SAM 3D Body runner")
    parser.add_argument("--repo_dir", required=True)
    parser.add_argument("--image_path", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--checkpoint_path", required=True)
    parser.add_argument("--mhr_path", required=True)
    args = parser.parse_args()

    repo_dir = Path(args.repo_dir).resolve()
    sys.path.insert(0, str(repo_dir))

    from sam_3d_body import SAM3DBodyEstimator, load_sam_3d_body

    image_path = Path(args.image_path).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    device = torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu")
    model, model_cfg = load_sam_3d_body(args.checkpoint_path, device=device, mhr_path=args.mhr_path)
    estimator = SAM3DBodyEstimator(
        sam_3d_body_model=model,
        model_cfg=model_cfg,
        human_detector=None,
        human_segmentor=None,
        fov_estimator=None,
    )
    outputs = estimator.process_one_image(str(image_path), inference_type="body")
    preview_path = output_dir / f"{image_path.stem}_sam3d_preview.jpg"
    pose_preview_path = output_dir / f"{image_path.stem}_sam3d_pose_preview.jpg"
    _draw_preview(image_path, outputs, pose_preview_path)
    mesh_paths = _export_meshes(outputs, estimator.faces, output_dir, image_path.stem)
    if mesh_paths:
        _render_mesh_preview(mesh_paths[0], preview_path)
    else:
        preview_path.write_bytes(pose_preview_path.read_bytes())
    metadata = {
        "person_count": len(outputs),
        "preview_path": str(preview_path),
        "pose_preview_path": str(pose_preview_path),
        "mesh_paths": mesh_paths,
        "outputs": [
            {
                "bbox": _jsonable(person.get("bbox")),
                "focal_length": _jsonable(person.get("focal_length")),
                "pred_cam_t": _jsonable(person.get("pred_cam_t")),
                "pred_keypoints_2d": _jsonable(person.get("pred_keypoints_2d")),
            }
            for person in outputs
        ],
    }
    metadata_path = output_dir / f"{image_path.stem}_sam3d_metadata.json"
    metadata_path.write_text(json.dumps(metadata, default=str))
    print(json.dumps({"preview_path": str(preview_path), "mesh_paths": mesh_paths, "metadata_path": str(metadata_path)}))


if __name__ == "__main__":
    main()
