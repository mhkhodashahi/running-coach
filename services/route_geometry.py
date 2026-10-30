"""Pure route geometry kept for the optional legacy map renderer."""

from __future__ import annotations

import math

import pandas as pd


def downsample_route(route: pd.DataFrame, max_points: int = 650) -> pd.DataFrame:
    if len(route) <= max_points:
        return route
    step = max(len(route) // max_points, 1)
    sampled = route.iloc[::step].copy()
    if sampled.index[-1] != route.index[-1]:
        sampled = pd.concat([sampled, route.tail(1)])
    return sampled


def encode_polyline(points: list[dict[str, float]]) -> str:
    encoded = []
    previous_lat = 0
    previous_lng = 0
    for point in points:
        lat = int(round(float(point["lat"]) * 100000))
        lng = int(round(float(point["lng"]) * 100000))
        for value in (lat - previous_lat, lng - previous_lng):
            shifted = value << 1
            if value < 0:
                shifted = ~shifted
            while shifted >= 0x20:
                encoded.append(chr((0x20 | (shifted & 0x1F)) + 63))
                shifted >>= 5
            encoded.append(chr(shifted + 63))
        previous_lat = lat
        previous_lng = lng
    return "".join(encoded)


def route_heading_degrees(points: list[dict[str, float]]) -> float:
    if len(points) < 2:
        return 0.0
    start, end = points[0], points[-1]
    lat1, lat2 = math.radians(start["lat"]), math.radians(end["lat"])
    delta_lng = math.radians(end["lng"] - start["lng"])
    y = math.sin(delta_lng) * math.cos(lat2)
    x = (math.cos(lat1) * math.sin(lat2)) - (math.sin(lat1) * math.cos(lat2) * math.cos(delta_lng))
    return (math.degrees(math.atan2(y, x)) + 360) % 360
