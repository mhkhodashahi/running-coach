"""Dashboard context and explicit widget actions; no LLM or plan writes."""

from __future__ import annotations

from datetime import date

from pydantic import ValidationError

from config import Settings
from services.timeline_notes import read_notes
from web.dashboard.charts import REGISTRY, load_source
from web.dashboard.storage import Widget, WidgetOptions, read_widgets, save_widgets
from web.today import sync_label
from web.view_models.dashboard import follow_ups, panel_summary, widget_view, widget_window


def context(settings: Settings, day: date, days: int) -> dict:
    if days not in (28, 90, 365):
        raise ValueError("Choose 28, 90 or 365 days")
    widgets = read_widgets(settings.db_path, settings.default_user_id)
    source = load_source(settings, day)
    sync = sync_label(settings, day)
    windows = [widget_window(day, days, widget) for widget in widgets]
    notes = (read_notes(settings.db_path, settings.default_user_id,
                        min(start for start, _ in windows), max(end for _, end in windows)) if windows else ())
    views = [widget_view(widget, source, day, days, index, sync, notes)
             for index, widget in enumerate(widgets)]
    return {"widgets": views, "definitions": REGISTRY, "range_days": days,
            "sync": sync, "panel_summary": panel_summary(views), "panel_follow_ups": follow_ups(views),
            "dashboard": True, "as_of": day.isoformat()}


OVERVIEW_CHARTS = {
    "Recovery": ("recovery_trends", None),
    "Resting HR": ("recovery_trends", "resting_hr"),
    "HRV": ("recovery_trends", "hrv"),
    "Sleep": ("sleep_vs_recovery", None),
    "Weekly load": ("weekly_load", None),
}


def add_overview_card(settings: Settings, title: str, days: int) -> bool:
    """Materialize defaults only on an actual edit; do not add the same chart twice."""
    if title not in OVERVIEW_CHARTS or days not in (7, 28, 90):
        raise ValueError("Unknown Insights card or range")
    chart_id, metric = OVERVIEW_CHARTS[title]
    options = WidgetOptions(range=str(days), recovery_metric=metric)
    widgets = read_widgets(settings.db_path, settings.default_user_id)
    if any(widget.chart_id == chart_id and widget.options == options for widget in widgets):
        return False
    widgets.append(Widget(chart_id=chart_id, options=options))
    save_widgets(settings.db_path, settings.default_user_id, widgets)
    return True


def _position(widgets: list[Widget], key: int) -> int:
    for index, widget in enumerate(widgets):
        if key == (widget.id if widget.id is not None else -(index + 1)):
            return index
    raise ValueError("Chart not found")


def change(settings: Settings, action: str, key: int | None = None, chart_id: str | None = None,
           options: dict | None = None) -> None:
    widgets = read_widgets(settings.db_path, settings.default_user_id)
    if action == "add":
        if chart_id in REGISTRY and not options:
            options = {"size": REGISTRY[chart_id].default_size}
        widget = Widget.model_validate({"chart_id": chart_id, "options": options or {}})
        widgets.append(widget)
    else:
        if key is None:
            raise ValueError("Chart not found")
        index = _position(widgets, key)
        widget = widgets[index]
        if action == "edit":
            widgets[index] = Widget(id=widget.id, chart_id=widget.chart_id,
                                    options=WidgetOptions.model_validate(options or {}))
        elif action == "duplicate":
            widgets.insert(index + 1, widget.model_copy(update={"id": None}))
        elif action == "remove":
            widgets.pop(index)
        elif action in ("up", "down"):
            other = index + (-1 if action == "up" else 1)
            if 0 <= other < len(widgets):
                widgets[index], widgets[other] = widgets[other], widgets[index]
        else:
            raise ValueError("Unknown chart action")
    try:
        save_widgets(settings.db_path, settings.default_user_id, widgets)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


def one_widget(settings: Settings, day: date, days: int, key: int):
    if days not in (28, 90, 365):
        raise ValueError("Choose 28, 90 or 365 days")
    widgets = read_widgets(settings.db_path, settings.default_user_id)
    index = _position(widgets, key)
    start, end = widget_window(day, days, widgets[index])
    notes = read_notes(settings.db_path, settings.default_user_id, start, end)
    return widget_view(widgets[index], load_source(settings, day), day, days, index, sync_label(settings, day), notes)
