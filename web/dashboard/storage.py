"""Validate and persist a complete ordered widget layout."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from db.repositories.dashboard_widgets import DashboardWidgetRepository
from db.session import session_scope

CHART_IDS = (
    "planned_vs_done", "intensity_share", "best_efforts", "pace_vs_hr_easy",
    "sleep_vs_recovery", "weekly_load", "training_mix", "recovery_trends",
)
DEFAULT_CHARTS = ("recovery_trends", "weekly_load", "intensity_share", "training_mix")
MAX_WIDGETS = 20


class WidgetOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=80)
    range: Literal["dashboard", "7", "28", "90", "365", "custom"] = "dashboard"
    from_date: date | None = None
    to_date: date | None = None
    sport: Literal["running", "volleyball", "football", "gym", "other"] | None = None
    size: Literal["half", "full"] = "half"
    measure: Literal["duration", "load"] | None = None
    moving_average: bool | None = None
    usual_range: bool | None = None
    distance_km: Literal[1, 5, 10] | None = None
    recovery_metric: Literal["recovery", "resting_hr", "hrv"] | None = None

    @model_validator(mode="after")
    def valid_dates(self) -> WidgetOptions:
        if self.range == "custom":
            if not self.from_date or not self.to_date or self.from_date > self.to_date:
                raise ValueError("Custom range needs a from date no later than the to date")
            if (self.to_date - self.from_date).days > 365:
                raise ValueError("Custom range cannot exceed 365 days")
        elif self.from_date or self.to_date:
            raise ValueError("Custom dates require the custom range option")
        return self


class Widget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int | None = None
    chart_id: Literal[*CHART_IDS]
    options: WidgetOptions = Field(default_factory=WidgetOptions)

    @model_validator(mode="after")
    def allowed_options(self) -> Widget:
        allowed = {
            "planned_vs_done": {"measure"}, "intensity_share": {"sport", "moving_average"},
            "best_efforts": {"distance_km"}, "pace_vs_hr_easy": set(),
            "sleep_vs_recovery": set(), "weekly_load": set(), "training_mix": set(),
            "recovery_trends": {"recovery_metric", "moving_average", "usual_range"},
        }[self.chart_id]
        used = {key for key in ("sport", "measure", "moving_average", "usual_range", "distance_km", "recovery_metric")
                if getattr(self.options, key) is not None}
        if used - allowed:
            raise ValueError(f"Unsupported options for {self.chart_id}: {', '.join(sorted(used - allowed))}")
        return self


def defaults() -> list[Widget]:
    return [Widget(chart_id=chart_id) for chart_id in DEFAULT_CHARTS]


def read_widgets(database: Path, user_id: int) -> list[Widget]:
    url = f"sqlite:///file:{database.resolve()}?mode=ro&uri=true"
    with session_scope(url) as session:
        rows = DashboardWidgetRepository(session).list(user_id)
    if rows and rows[0]["chart_id"] == "__empty__":
        return []
    return ([Widget.model_validate({"id": row["id"], "chart_id": row["chart_id"],
                                    "options": json.loads(row["config_json"])})
             for row in rows] if rows else defaults())


def save_widgets(database: Path, user_id: int, widgets: list[Widget]) -> list[Widget]:
    if len(widgets) > MAX_WIDGETS:
        raise ValueError(f"At most {MAX_WIDGETS} charts are allowed")
    now = datetime.now(UTC).replace(tzinfo=None)
    data = [{"id": widget.id, "chart_id": widget.chart_id,
             "config_json": json.dumps(widget.options.model_dump(mode="json"), separators=(",", ":"))}
            for widget in widgets]
    with session_scope(f"sqlite:///{database.resolve()}") as session:
        saved = DashboardWidgetRepository(session).replace(user_id, data, now)
    return [Widget.model_validate({"id": item["id"], "chart_id": item["chart_id"],
                                   "options": json.loads(item["config_json"])}) for item in saved]
