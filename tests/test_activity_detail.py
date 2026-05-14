from __future__ import annotations

import pandas as pd

from services.hr_zones import heart_rate_zone_summary, supports_hr_zone_view


def test_heart_rate_zone_summary_uses_elapsed_time_between_samples() -> None:
    track_points = pd.DataFrame(
        {
            "point_index": [0, 1, 2],
            "elapsed_seconds": [0, 60, 180],
            "heart_rate": [115, 145, 175],
        }
    )

    summary = heart_rate_zone_summary(track_points, 190)

    z2 = summary.loc[summary["zone"].astype(str) == "Z2 Easy"].iloc[0]
    z3 = summary.loc[summary["zone"].astype(str) == "Z3 Steady"].iloc[0]
    z5 = summary.loc[summary["zone"].astype(str) == "Z5 Max"].iloc[0]
    assert z2["seconds"] == 60
    assert z3["seconds"] == 120
    assert z5["seconds"] == 90


def test_hr_zone_view_supports_running_and_football() -> None:
    assert supports_hr_zone_view("running")
    assert supports_hr_zone_view("football")
    assert supports_hr_zone_view("soccer")
    assert not supports_hr_zone_view("cycling")
