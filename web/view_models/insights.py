"""Pure presentation choices for dated Insights data."""

from __future__ import annotations

from typing import Any

from web.charts import trend_bars, trend_line, weekly_percent_bars
from web.formatting import sleep_hours
from web.view_models.today import dial_status


def latest(values: list[tuple[str, float | None]]) -> float | None:
    return next((value for _, value in reversed(values) if value is not None), None)


def gap_note(values: list[tuple[str, float | None]]) -> str | None:
    missing = sum(value is None for _, value in values)
    return f"{missing} {'day' if missing == 1 else 'days'} without data" if missing else None


def _signed(value: float, unit: str) -> str:
    amount = round(value)
    sign = "+" if amount > 0 else "\u2212" if amount < 0 else ""
    return f"{sign}{abs(amount)} {unit}"


def summary_sentences(series: dict[str, list[tuple[str, float | None]]],
                      baselines: dict[str, list[tuple[str, float | None]]],
                      load_percent: int | None, sync: str) -> str:
    comparisons = []
    for key, label, multiplier, unit in (("rhr", "Resting HR", 1, "bpm"),
                                          ("hrv", "HRV", 1, "ms"),
                                          ("sleep", "Sleep", 60, "min")):
        value = latest(series[key])
        usual = latest(baselines[key]) if key in baselines else None
        if value is not None and usual is not None:
            comparisons.append(f"{label} {_signed((value - usual) * multiplier, unit)} vs usual")
    first = "Recovery: " + "; ".join(comparisons[:2]) + "." if comparisons else f"Recovery: No data · {sync}."
    if load_percent is not None:
        second = f"This week's load is {load_percent}% of usual."
    elif len(comparisons) > 2:
        second = comparisons[2] + "."
    else:
        second = f"Training load: No data · {sync}."
    return first + " " + second


def _status(kind: str, value: float | None, usual: float | None) -> tuple[str, str]:
    return dial_status(kind, value, usual)


def _card(title: str, value: float | None, usual: float | None, display: str | None,
          status_kind: str, chart: dict[str, str], series: list[tuple[str, float | None]],
          sync: str) -> dict[str, Any]:
    status, icon = _status(status_kind, value, usual)
    if value is None:
        status, icon = "No data", "help"
    usual_display = None
    if usual is not None:
        usual_display = (f"usual {sleep_hours(usual)}" if title == "Sleep" else
                         f"usual {round(usual)} bpm" if title == "Resting HR" else
                         f"usual {round(usual)} ms" if title == "HRV" else None)
    return {"title": title, "value": display or "No data", "status": status, "icon": icon,
            "usual": usual_display,
            "chart": chart, "gap_note": gap_note(series), "missing": sync if value is None else None}


def _follow_ups(load_status: str) -> tuple[str, ...]:
    if load_status == "Above usual":
        return ("What raised my load?", "How has recovery changed?", "Should I ease back this week?")
    if load_status == "Below usual":
        return ("How has recovery changed?", "Is there room for an easy run?", "Compare with last month")
    return ("How has recovery changed?", "What changed in my sleep?", "Compare with last month")


def panel_summary(series: dict[str, list[tuple[str, float | None]]],
                  baselines: dict[str, list[tuple[str, float | None]]],
                  load_percent: int | None, sync: str) -> str:
    hrv, usual_hrv = latest(series["hrv"]), latest(baselines["hrv"])
    rhr, usual_rhr = latest(series["rhr"]), latest(baselines["rhr"])
    parts = []
    if hrv is not None and usual_hrv is not None:
        parts.append(f"HRV is {_signed(hrv - usual_hrv, 'ms')} vs usual")
    if rhr is not None and usual_rhr is not None:
        parts.append(f"resting HR is {_signed(rhr - usual_rhr, 'bpm')} vs usual")
    if not parts:
        return f"Recovery: No data · {sync}."
    text = " while ".join(parts)
    text = text[:1].upper() + text[1:] + "."
    if load_percent is not None:
        text += f" Load is {load_percent}% of usual."
    return text


def build_insights_view(data: dict[str, Any], goal: tuple[str, float] | None,
                        runs: list[tuple[float, float]], sleep_goal: float | None) -> dict[str, Any]:
    """No model calls, DB access, or new training metrics."""
    series = data["series"]
    baselines = data["baselines"]
    sync = data["sync"]
    weekly = data["weekly"]
    reference = data["reference"]
    weeks = [(stamp, round(sum(values.values()) / reference * 100)
              if values and reference and reference > 0 else None)
             for stamp, values in sorted(weekly.items())]
    load_percent = weeks[-1][1] if weeks else None
    load_status, load_icon = _status("load", float(load_percent) if load_percent is not None else None, 100)
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
        {"title": "Weekly load", "value": f"{load_percent}% of usual" if load_percent is not None else "No data",
         "status": load_status, "icon": load_icon, "usual": None,
         "chart": weekly_percent_bars(weeks), "gap_note": None,
         "missing": sync if load_percent is None else None},
    )
    goal_view = None
    if goal and ("running" in goal[0] or goal[0].endswith("_pb")):
        goal_view = {"title": f"Running · {goal[1]:g}K goal", "runs": len(runs),
                     "distance": f"{sum(distance for distance, _ in runs):.1f} km",
                     "longest": f"{round(max((duration for _, duration in runs), default=0))} min"}
    return {**data, "summary_text": summary_sentences(series, baselines, load_percent, sync),
            "metric_cards": cards, "goal_view": goal_view,
            "panel_summary": panel_summary(series, baselines, load_percent, sync),
            "panel_follow_ups": _follow_ups(load_status)}
