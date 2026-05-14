"""Heart-rate zone analysis helpers."""

from __future__ import annotations

import pandas as pd

HR_ZONE_COLORS = {
    "Z1 Recovery": "#60a5fa",
    "Z2 Easy": "#22c55e",
    "Z3 Steady": "#f59e0b",
    "Z4 Threshold": "#f97316",
    "Z5 Max": "#ef4444",
}


def supports_hr_zone_view(activity_type: str | None) -> bool:
    """Return whether an activity type should show HR zone analysis."""

    normalized = str(activity_type or "").lower()
    return any(keyword in normalized for keyword in ("run", "trail", "treadmill", "football", "soccer"))


def heart_rate_zone_bounds(max_hr: int | None) -> list[tuple[str, float, float]]:
    """Return Garmin-style percentage-based HR zones."""

    max_hr = int(max_hr or 188)
    return [
        ("Z1 Recovery", 0.50 * max_hr, 0.60 * max_hr),
        ("Z2 Easy", 0.60 * max_hr, 0.70 * max_hr),
        ("Z3 Steady", 0.70 * max_hr, 0.80 * max_hr),
        ("Z4 Threshold", 0.80 * max_hr, 0.90 * max_hr),
        ("Z5 Max", 0.90 * max_hr, float("inf")),
    ]


def heart_rate_zone_summary(track_points: pd.DataFrame, max_hr: int | None) -> pd.DataFrame:
    """Summarize time spent in each HR zone from Garmin stream samples."""

    if track_points.empty or "heart_rate" not in track_points:
        return pd.DataFrame(columns=["zone", "range", "seconds", "minutes", "percent"])

    samples = track_points.copy()
    samples["heart_rate"] = pd.to_numeric(samples["heart_rate"], errors="coerce")
    samples["elapsed_seconds"] = pd.to_numeric(samples.get("elapsed_seconds"), errors="coerce")
    sort_column = "point_index" if "point_index" in samples else "elapsed_seconds"
    samples = samples.dropna(subset=["heart_rate"]).sort_values(sort_column)
    if samples.empty:
        return pd.DataFrame(columns=["zone", "range", "seconds", "minutes", "percent"])

    elapsed = samples["elapsed_seconds"]
    if elapsed.notna().sum() >= 2:
        seconds = elapsed.diff().shift(-1)
        median_step = seconds[(seconds > 0) & (seconds <= 120)].median()
        fallback_step = float(median_step) if pd.notna(median_step) else 1.0
        samples["sample_seconds"] = seconds.where((seconds > 0) & (seconds <= 300), fallback_step)
    else:
        samples["sample_seconds"] = 1.0

    max_hr_value = int(max_hr or 188)
    bounds = heart_rate_zone_bounds(max_hr_value)

    def assign_zone(heart_rate: float) -> str:
        for zone, lower, upper in bounds:
            if lower <= heart_rate < upper:
                return zone
        return "Below Z1"

    samples["zone"] = samples["heart_rate"].apply(assign_zone)
    grouped = samples.groupby("zone", as_index=False)["sample_seconds"].sum().rename(columns={"sample_seconds": "seconds"})
    zone_order = [zone for zone, _, _ in bounds]
    grouped["zone"] = pd.Categorical(grouped["zone"], categories=zone_order + ["Below Z1"], ordered=True)
    grouped = grouped.sort_values("zone")
    total_seconds = float(grouped["seconds"].sum()) or 1.0
    grouped["minutes"] = grouped["seconds"] / 60
    grouped["percent"] = grouped["seconds"] / total_seconds * 100
    range_labels = {
        zone: f"{lower:.0f}-{upper - 1:.0f} bpm" if upper != float("inf") else f"{lower:.0f}+ bpm"
        for zone, lower, upper in bounds
    }
    range_labels["Below Z1"] = f"<{0.50 * max_hr_value:.0f} bpm"
    grouped["range"] = grouped["zone"].astype(str).map(range_labels)
    return grouped[["zone", "range", "seconds", "minutes", "percent"]]
