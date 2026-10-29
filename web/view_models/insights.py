"""Pure presentation choices for dated Insights data."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from statistics import pstdev
from typing import Any

from web.charts import plot_only, trend_bars, trend_line, weekly_percent_bars
from web.formatting import short_date, sleep_hours
from web.view_models.today import dial_status

MIN_MEANINGFUL_CHANGE = {"rhr": 1.0, "hrv": 3.0, "sleep": 15.0}


@dataclass(frozen=True)
class RangeChange:
    label: str
    amount: int
    unit: str
    direction: str
    strength: float


def latest(values: list[tuple[str, float | None]]) -> float | None:
    return next((value for _, value in reversed(values) if value is not None), None)


def gap_note(values: list[tuple[str, float | None]]) -> str | None:
    missing = sum(value is None for _, value in values)
    return f"{missing} {'day' if missing == 1 else 'days'} without data" if missing else None


def axis_dates(values: list[tuple[str, float | None]], limit: int = 5) -> tuple[str, ...]:
    """At most five evenly spaced dates, including both ends."""
    if not values:
        return ()
    count = min(limit, len(values))
    indices = sorted({round(index * (len(values) - 1) / max(count - 1, 1)) for index in range(count)})
    return tuple(short_date(values[index][0]) for index in indices)


def _range_changes(series: dict[str, list[tuple[str, float | None]]],
                   previous: dict[str, list[tuple[str, float | None]]]
                   ) -> tuple[list[RangeChange], bool]:
    """Compare only sufficiently covered periods; rank change against usual variation."""
    changes: list[RangeChange] = []
    covered = False
    for key, label, unit, multiplier in (("rhr", "Resting HR", "bpm", 1),
                                          ("hrv", "HRV", "ms", 1),
                                          ("sleep", "Sleep", "min", 60)):
        current = [value for _, value in series.get(key, []) if value is not None]
        earlier = [value for _, value in previous.get(key, []) if value is not None]
        needed = ceil(len(series.get(key, [])) / 2)
        if not needed or len(current) < needed or len(earlier) < needed:
            continue
        covered = True
        delta = (sum(current) / len(current) - sum(earlier) / len(earlier)) * multiplier
        variation = max(MIN_MEANINGFUL_CHANGE[key], pstdev(earlier) * multiplier)
        amount = round(delta)
        if amount == 0 or abs(delta) <= variation:
            continue
        direction = ("longer" if key == "sleep" else "higher") if delta > 0 else (
            "shorter" if key == "sleep" else "lower")
        changes.append(RangeChange(label, abs(amount), unit, direction, abs(delta) / variation))
    return changes, covered


def summary_sentences(series: dict[str, list[tuple[str, float | None]]],
                      previous: dict[str, list[tuple[str, float | None]]],
                      load_percent: int | None, sync: str) -> str:
    del sync
    days = len(series.get("rhr", []))
    changes, covered = _range_changes(series, previous)
    if not covered:
        return f"Not enough data in the previous {days} days to compare."
    if changes:
        phrases = [f"{item.label} averaged {item.amount} {item.unit} {item.direction}"
                   for item in changes]
        joined = (phrases[0] if len(phrases) == 1 else
                  " and ".join(phrases) if len(phrases) == 2 else
                  ", ".join(phrases[:-1]) + ", and " + phrases[-1])
        first = f"{joined} than the previous {days} days."
    else:
        first = f"Nothing changed much compared with the previous {days} days."
    if load_percent is None:
        return first
    load = "about half of usual" if 45 <= load_percent <= 55 else f"{load_percent}% of usual"
    return f"{first} Load this week is {load}."


def _status(kind: str, value: float | None, usual: float | None) -> tuple[str, str]:
    return dial_status(kind, value, usual)


def _card(title: str, value: float | None, usual: float | None, display: str | None,
          status_kind: str, chart: dict[str, Any], series: list[tuple[str, float | None]],
          sync: str) -> dict[str, Any]:
    status, icon = _status(status_kind, value, usual)
    if value is None:
        status, icon = "No data", "help"
    usual_display = None
    if usual is not None:
        usual_display = (f"usual {sleep_hours(usual)}" if title == "Sleep" else
                         f"usual {round(usual)} bpm" if title == "Resting HR" else
                         f"usual {round(usual)} ms" if title == "HRV" else None)
    low, high = chart.get("y_min"), chart.get("y_max")
    unit = "%" if title == "Weekly load" else " bpm" if title == "Resting HR" else (
        " ms" if title == "HRV" else " h" if title == "Sleep" else "")
    last_stamp = next((stamp for stamp, item in reversed(series) if item is not None), None)
    current_stamp = series[-1][0] if series else None
    caption = ("this week" if title == "Weekly load" and value is not None else
               "today" if title in ("Recovery", "Resting HR") and last_stamp == current_stamp else
               "last night" if title in ("Sleep", "HRV") and last_stamp == current_stamp else
               f"latest: {short_date(last_stamp)}" if last_stamp else f"No data · {sync}")
    def axis_value(item: float | None) -> str:
        return f"{round(item)}{unit}" if item is not None else ""
    return {"title": title, "value": display or "No data", "caption": caption,
            "status": status, "icon": icon,
            "usual": usual_display,
            "chart": {**chart, "svg": plot_only(chart["svg"]) if chart["svg"] else ""},
            "axis_dates": axis_dates(series), "axis_high": axis_value(high),
            "axis_low": axis_value(low),
            "gap_note": gap_note(series), "missing": sync if value is None else None}


def _follow_ups(load_status: str) -> tuple[str, ...]:
    if load_status == "Above usual":
        return ("What raised my load?", "How has recovery changed?", "Should I ease back this week?")
    if load_status == "Below usual":
        return ("How has recovery changed?", "Is there room for an easy run?", "Compare with last month")
    return ("How has recovery changed?", "What changed in my sleep?", "Compare with last month")


def panel_summary(series: dict[str, list[tuple[str, float | None]]],
                  previous: dict[str, list[tuple[str, float | None]]], sync: str) -> str:
    del sync
    days = len(series.get("rhr", []))
    changes, covered = _range_changes(series, previous)
    if not covered:
        return f"Not enough data in the previous {days} days to compare."
    if not changes:
        return f"Nothing changed much compared with the previous {days} days."
    strongest = max(changes, key=lambda item: item.strength)
    label = strongest.label[0].lower() + strongest.label[1:]
    return (f"The clearest shift is {label}: {strongest.amount} "
            f"{strongest.unit} {strongest.direction} than the previous {days} days.")


def build_insights_view(data: dict[str, Any], goal: tuple[str, float] | None,
                        runs: list[tuple[float, float]], sleep_goal: float | None) -> dict[str, Any]:
    """No model calls, DB access, or new training metrics."""
    series = data["series"]
    baselines = data["baselines"]
    previous = data.get("previous", {})
    sync = data["sync"]
    weekly = data["weekly"]
    reference = data["reference"]
    weeks = [(stamp, round(sum(values.values()) / reference * 100)
              if values and reference and reference > 0 else None)
             for stamp, values in sorted(weekly.items())]
    building = {stamp for stamp, count in data.get("reference_week_counts", {}).items() if count < 4}
    load_percent = weeks[-1][1] if weeks else None
    load_status, _ = _status("load", float(load_percent) if load_percent is not None else None, 100)
    cards = (
        _card("Recovery", latest(series["readiness"]), None,
              f"{round(latest(series['readiness']))}" if latest(series["readiness"]) is not None else None,
              "recovery", trend_line(series["readiness"], "Recovery", "muted"), series["readiness"], sync),
        _card("Sleep", latest(series["sleep"]), latest(baselines.get("sleep", [])),
              sleep_hours(latest(series["sleep"])), "sleep",
              trend_bars(series["sleep"], "Sleep", sleep_goal if sleep_goal and sleep_goal > 0 else None, "sleep"),
              series["sleep"], sync),
        _card("Resting HR", latest(series["rhr"]), latest(baselines["rhr"]),
              f"{round(latest(series['rhr']))} bpm" if latest(series["rhr"]) is not None else None,
              "sleep", trend_line(series["rhr"], "Resting HR", "heart", baselines["rhr"], unit="bpm"),
              series["rhr"], sync),
        _card("HRV", latest(series["hrv"]), latest(baselines["hrv"]),
              f"{round(latest(series['hrv']))} ms" if latest(series["hrv"]) is not None else None,
              "sleep", trend_line(series["hrv"], "HRV", "sleep", baselines["hrv"], unit="ms"),
              series["hrv"], sync),
        {**_card("Weekly load", float(load_percent) if load_percent is not None else None, 100,
                 f"{load_percent}% of usual" if load_percent is not None else None,
                 "load", weekly_percent_bars(weeks, building), weeks, sync),
         "baseline_note": "baseline still building" if building else None},
    )
    goal_view = None
    if goal and ("running" in goal[0] or goal[0].endswith("_pb")):
        goal_view = {"title": f"Running · {goal[1]:g}K goal", "runs": len(runs),
                     "distance": f"{sum(distance for distance, _ in runs):.1f} km",
                     "longest": f"{round(max((duration for _, duration in runs), default=0))} min"}
    return {**data, "summary_text": summary_sentences(series, previous, load_percent, sync),
            "metric_cards": cards, "goal_view": goal_view,
            "panel_summary": panel_summary(series, previous, sync),
            "panel_follow_ups": _follow_ups(load_status)}
