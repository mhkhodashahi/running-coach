"""Pose landmark metric helpers shared by body scan processors."""

from __future__ import annotations

import math
from typing import Any

Point = dict[str, float]


def average_visibility(landmarks: list[dict[str, Any]], threshold: float = 0.5) -> tuple[float, int]:
    """Return average landmark visibility and visible landmark count."""

    if not landmarks:
        return 0.0, 0
    values = [float(point.get("visibility", 0.0) or 0.0) for point in landmarks]
    visible = sum(1 for value in values if value >= threshold)
    return round(sum(values) / len(values), 3), visible


def tilt_degrees(left: Point, right: Point) -> float:
    """Return absolute tilt in degrees between two normalized image points."""

    dx = float(right["x"]) - float(left["x"])
    dy = float(right["y"]) - float(left["y"])
    if dx == 0:
        return 90.0
    return round(abs(math.degrees(math.atan2(dy, dx))), 2)


def normalized_distance(first: Point, second: Point) -> float:
    """Return normalized 2D distance between two landmark points."""

    dx = float(second["x"]) - float(first["x"])
    dy = float(second["y"]) - float(first["y"])
    return round(math.hypot(dx, dy), 4)


def midpoint(first: Point, second: Point) -> Point:
    """Return midpoint for two normalized landmark points."""

    return {
        "x": (float(first["x"]) + float(second["x"])) / 2,
        "y": (float(first["y"]) + float(second["y"])) / 2,
        "z": (float(first.get("z", 0.0)) + float(second.get("z", 0.0))) / 2,
    }


def torso_lean_degrees(shoulder_midpoint: Point, hip_midpoint: Point) -> float:
    """Estimate torso lean from vertical using shoulder and hip midpoints."""

    dx = float(shoulder_midpoint["x"]) - float(hip_midpoint["x"])
    dy = float(hip_midpoint["y"]) - float(shoulder_midpoint["y"])
    if dy == 0:
        return 90.0
    return round(math.degrees(math.atan2(dx, dy)), 2)


def joint_angle_degrees(first: Point, middle: Point, third: Point) -> float:
    """Return angle at the middle point for three normalized points."""

    vector_a = (float(first["x"]) - float(middle["x"]), float(first["y"]) - float(middle["y"]))
    vector_b = (float(third["x"]) - float(middle["x"]), float(third["y"]) - float(middle["y"]))
    norm_a = math.hypot(*vector_a)
    norm_b = math.hypot(*vector_b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    cosine = max(-1.0, min(1.0, (vector_a[0] * vector_b[0] + vector_a[1] * vector_b[1]) / (norm_a * norm_b)))
    return round(math.degrees(math.acos(cosine)), 2)
