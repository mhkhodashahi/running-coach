"""Pure dashboard presentation, option windows and chart/table parity."""

from __future__ import annotations

from datetime import date, timedelta

from web.charts import dashboard_svg
from web.dashboard.charts import REGISTRY, DashboardSource
from web.dashboard.storage import Widget
from web.formatting import short_date


def widget_window(day: date, dashboard_days: int, widget: Widget) -> tuple[date, date]:
    options = widget.options
    if options.range == "custom":
        return options.from_date, options.to_date
    days = dashboard_days if options.range == "dashboard" else int(options.range)
    return day - timedelta(days=days - 1), day


def widget_title(widget: Widget) -> str:
    if widget.options.title:
        return widget.options.title
    if widget.chart_id == "best_efforts":
        return f"Best efforts · {widget.options.distance_km or 5} km"
    if widget.chart_id == "intensity_share":
        return f"Intensity share · {(widget.options.sport or 'running').title()}"
    if widget.chart_id == "recovery_trends" and widget.options.recovery_metric not in (None, "recovery"):
        label = "Resting HR" if widget.options.recovery_metric == "resting_hr" else "HRV"
        return f"{label} trends"
    return REGISTRY[widget.chart_id].title


def widget_view(widget: Widget, source: DashboardSource, day: date, dashboard_days: int,
                position: int, sync: str, notes: tuple[dict, ...] = ()) -> dict:
    definition = REGISTRY[widget.chart_id]
    start, end = widget_window(day, dashboard_days, widget)
    data = definition.data_function(source, start, end, widget.options)
    title = widget_title(widget)
    relevant_notes = tuple(note for note in notes if start.isoformat() <= note["date"] <= end.isoformat())
    rendered = dashboard_svg(data.rows, data.columns, definition.chart_type, title, relevant_notes)
    table_rows = []
    covered: set[str] = set()
    for row in data.rows:
        stamp = str(row[data.columns[0]])[:10]
        interval_end = (date.fromisoformat(stamp) + timedelta(days=6)).isoformat() if data.columns[0] == "Week" else stamp
        matching = [note for note in relevant_notes if stamp <= note["date"] <= interval_end]
        covered.update(note["date"] for note in matching)
        table_rows.append({**row, "Notes": "; ".join(note["text"] for note in matching)})
    for note in relevant_notes:
        if note["date"] not in covered:
            table_rows.append({data.columns[0]: note["date"], "Notes": note["text"]})
    table_rows.sort(key=lambda row: str(row[data.columns[0]]))
    sport = widget.options.sport or ("running" if widget.chart_id == "intensity_share" else "training")
    legends = {
        "planned_vs_done": (("Planned", "muted"), ("Done in plan", "load"),
                            ("Done beyond plan", "load-dark")),
        "intensity_share": (("Z1–Z2", "muted"), ("Z3+", "load")),
        "training_mix": (("Running", "muted"), ("Volleyball", "load"),
                         ("Football", "load-dark"), ("Gym", "sleep"), ("Other", "heart")),
    }
    legend = legends.get(widget.chart_id, ())
    if ((widget.chart_id == "intensity_share" and widget.options.moving_average is True)
            or (widget.chart_id == "recovery_trends" and widget.options.moving_average is not False)):
        legend = (*legend, ("Moving average", "ink" if widget.chart_id == "intensity_share" else "muted"))
    return {"key": str(widget.id if widget.id is not None else -(position + 1)),
            "chart_id": widget.chart_id, "title": title,
            "options": widget.options,
            "period": f"{short_date(start)} – {short_date(end)}", "size": widget.options.size,
            "svg": rendered["svg"], "summary": rendered["summary"], "columns": data.columns,
            "rows": data.rows, "table_columns": (*data.columns, "Notes"), "table_rows": tuple(table_rows),
            "notes": relevant_notes, "footnote": data.footnote, "legend": legend,
            "empty": f"No data for {sport} in this period · {sync}" if not rendered["svg"] else None}


def chart_context_summary(view: dict) -> str:
    """Code-written context only; the model is called later, on send."""
    numeric = next((column for column in view["columns"][1:] if any(
        isinstance(row.get(column), (int, float)) for row in view["rows"])), None)
    values = [float(row[numeric]) for row in view["rows"] if numeric and isinstance(row.get(numeric), (int, float))]
    if not values:
        return f"{view['title']} · {view['period']}. No measured data in this period."
    direction = "higher" if values[-1] > values[0] else "lower" if values[-1] < values[0] else "steady"
    usual = next((float(row["Usual high"]) for row in reversed(view["rows"])
                  if isinstance(row.get("Usual high"), (int, float))), None)
    usual_text = f" Usual upper range {usual:g}." if usual is not None else ""
    return (f"{view['title']} · {view['period']}. Latest {numeric} {values[-1]:g}; "
            f"{direction} than the start of the period.{usual_text}")


def panel_summary(views: list[dict]) -> str:
    state = dashboard_state(views)
    if state == "building":
        return "Your usual week baseline is still building."
    if state == "above":
        return "Your recent weekly load is above the 110% weekly limit."
    if state == "below":
        return "Your recent weekly load is below usual."
    if state == "normal":
        return "Your recent weekly load is near your usual level."
    return "Add charts to compare your recent training and recovery." if not views else (
        "Your dashboard shows the available training and recovery history.")


def dashboard_state(views: list[dict]) -> str:
    weekly = next((view for view in views if view["chart_id"] == "weekly_load"), None)
    if not weekly:
        return "missing"
    latest = next((row["% of usual"] for row in reversed(weekly["rows"])
                   if row["% of usual"] is not None), None)
    if latest is None:
        return "building"
    return "above" if latest > 110 else "below" if latest < 80 else "normal"


def follow_ups(views: list[dict]) -> tuple[str, str, str]:
    state = dashboard_state(views)
    if state == "missing":
        return ("How has my load changed?", "What does my Recovery show?", "Compare my recent sessions")
    if state == "building":
        return ("What can I learn from recent sessions?", "How is my Recovery changing?",
                "Which training data is missing?")
    if state == "above":
        return ("Should I reduce training this week?", "How is my Recovery changing?",
                "What was my hardest session?")
    if state == "below":
        return ("Can I add an easy session?", "How is my Recovery changing?",
                "How does this week compare?")
    return ("Is my weekly load safe?", "What changed in my Recovery?", "Which sport have I done most?")
