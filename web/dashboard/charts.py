"""Read-only chart registry and dated data, with no new metric formulas."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import mean, pstdev

from coach.planning import monday, usual_week, weekly_load_reference
from config import Settings
from metrics.load import calibration_and_scales, session_metrics
from metrics.reader import read_inputs
from metrics.snapshot import build_daily_snapshot
from metrics.sports import sport_category
from services.coach_facts import detect_intent
from web.dashboard.storage import WidgetOptions
from web.view_models.insights import MIN_MEANINGFUL_CHANGE

Row = dict[str, str | float | None]


@dataclass(frozen=True)
class ChartData:
    columns: tuple[str, ...]
    rows: tuple[Row, ...]
    footnote: str = ""


@dataclass(frozen=True)
class ChartDefinition:
    id: str
    title: str
    purpose: str
    data_function: Callable[[DashboardSource, date, date, WidgetOptions], ChartData]
    allowed_options: tuple[str, ...]
    default_size: str
    chart_type: str
    supports_usual_range: bool = False
    supports_moving_average: bool = False


@dataclass(frozen=True)
class DashboardSource:
    activities: tuple[dict, ...]
    plans: tuple[dict, ...]
    health: tuple[dict, ...]
    sessions: tuple[dict, ...]
    points: dict[int, tuple[tuple[float, float], ...]]
    laps: dict[int, tuple[dict, ...]]
    reference_rows: tuple[tuple[date, str, float | None], ...]
    settings: Settings
    day: date


def load_source(settings: Settings, day: date) -> DashboardSource:
    """Read bounded user-owned data once; the chart functions remain pure."""
    inputs = read_inputs(settings.db_path, settings.default_user_id, day,
                         settings.local_timezone, point_lookback_days=None)
    calibration, scales = calibration_and_scales(inputs.activities, inputs.profile,
                                                inputs.health, day, settings.local_timezone)
    sessions = []
    by_id = {}
    for activity in inputs.activities:
        result = session_metrics(activity, inputs.profile, inputs.health, day,
                                 settings.local_timezone, calibration, scales, settings.hr_zones)
        if result:
            zones = {zone.name.split()[0].upper(): zone.percent.value for zone in result.zones}
            entry = {"id": activity.id, "day": activity.day, "sport": sport_category(activity.type, day),
                     "duration": activity.duration, "load": result.load.value, "zones": zones,
                     "observed_minutes": (result.observed_seconds.value / 60
                                          if result.observed_seconds.value is not None else None),
                     "intent": None}
            sessions.append(entry)
            by_id[activity.id] = entry
    with sqlite3.connect(settings.db_path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        activities = tuple(dict(row) for row in connection.execute(
            "SELECT id,date,type,distance,duration,pace,avg_hr,planned_intent FROM activities "
            "WHERE user_id=? AND date<=? ORDER BY date,id", (settings.default_user_id, day.isoformat())))
        plans = tuple(dict(row) for row in connection.execute(
            "SELECT id,date,sport,intent,duration_min,status,linked_activity_id FROM plan_sessions "
            "WHERE user_id=? AND date<=?", (settings.default_user_id, day.isoformat())))
        health = tuple(dict(row) for row in connection.execute(
            "SELECT date,sleep_duration,resting_hr,hrv FROM health_metrics "
            "WHERE user_id=? AND date<=? ORDER BY date", (settings.default_user_id, day.isoformat())))
        points = {row["id"]: tuple((float(p[0]), float(p[1])) for p in connection.execute(
            "SELECT distance_km,elapsed_seconds FROM activity_track_points WHERE activity_id=? "
            "AND distance_km IS NOT NULL AND elapsed_seconds IS NOT NULL ORDER BY point_index", (row["id"],)))
            for row in activities if sport_category(row["type"], day) == "running"}
        laps = {row["id"]: tuple(dict(lap) for lap in connection.execute(
            "SELECT distance,duration,pace FROM activity_laps WHERE activity_id=? ORDER BY lap_index", (row["id"],)))
            for row in activities if sport_category(row["type"], day) == "running"}
    for row in activities:
        entry = by_id.get(row["id"])
        if not entry:
            continue
        # The intent rule uses the same zone shares as the opinion facts pack.
        zones = entry["zones"]
        low = sum(zones.get(name) or 0 for name in ("Z1", "Z2"))
        from services.hr_zones import heart_rate_zone_bounds

        maximum = inputs.profile.max_hr or (220 - inputs.profile.age if inputs.profile.age else None)
        bounds = settings.hr_zones or (heart_rate_zone_bounds(maximum) if maximum else ())
        facts = [{"id": key, "metric": key, "display": f"{value:.1f}%", "source": "activity zones"}
                 for key, value in (("Z1_Z2_SHARE", low),
                                    ("Z3_PLUS_SHARE", sum(zones.get(n) or 0 for n in ("Z3", "Z4", "Z5"))),
                                    ("Z3_Z4_SHARE", sum(zones.get(n) or 0 for n in ("Z3", "Z4"))),
                                    ("Z4_PLUS_SHARE", sum(zones.get(n) or 0 for n in ("Z4", "Z5"))))]
        if row["avg_hr"] is not None:
            facts.append({"id": "AVG_HR", "metric": "Avg HR", "display": f"{row['avg_hr']:.0f} bpm",
                          "source": "activities.avg_hr"})
        if len(bounds) >= 3:
            facts.extend(({"id": "Z2_LOWER_HALF_CAP", "metric": "Z2 half", "display":
                           f"{(bounds[1][1] + (bounds[1][2] or bounds[1][1])) / 2:.0f} bpm", "source": "zones"},
                          {"id": "Z3_UPPER_BPM", "metric": "Z3 high", "display": f"{bounds[2][2]} bpm",
                           "source": "zones"}))
        if row["planned_intent"] == "race":
            facts.append({"id": "PLAN_INTENT", "metric": "Planned", "display": "race", "source": "activities"})
        decision = detect_intent(facts, row["planned_intent"])
        entry["intent"] = decision.intent if decision else None
    references = tuple((entry["day"], "walking" if next(
        (row["type"] for row in activities if row["id"] == entry["id"]), "") == "walking" else entry["sport"],
                        entry["load"]) for entry in sessions)
    return DashboardSource(activities, plans, health, tuple(sessions), points, laps, references, settings, day)


def _week_keys(start: date, end: date) -> tuple[date, ...]:
    cursor = monday(start)
    result = []
    while cursor <= end:
        result.append(cursor)
        cursor += timedelta(days=7)
    return tuple(result)


def planned_vs_done(source: DashboardSource, start: date, end: date, options: WidgetOptions) -> ChartData:
    rows = []
    load = options.measure == "load"
    for week in _week_keys(start, end):
        plans = [item for item in source.plans if week <= date.fromisoformat(item["date"]) < week + timedelta(days=7)]
        done = [item for item in source.sessions if week <= item["day"] < week + timedelta(days=7)
                and item["sport"] not in ("excluded", "mobility")]
        if not plans and not done:
            continue
        def amount(item: dict) -> float | None:
            if not load:
                return float(item["duration"]) if item["duration"] is not None else None
            return float(item["load"]) if item["load"] is not None else None
        def total(items: list[dict]) -> float | None:
            amounts = [amount(item) for item in items]
            return sum(amounts) if all(value is not None for value in amounts) else None
        linked = {item["linked_activity_id"] for item in plans if item["linked_activity_id"]}
        open_plans = [item for item in plans if item["linked_activity_id"] is None]
        for item in done:
            if item["id"] in linked:
                continue
            match = next((plan for plan in open_plans if plan["date"] == item["day"].isoformat()
                          and plan["sport"] == item["sport"]), None)
            if match:
                linked.add(item["id"])
                open_plans.remove(match)
        done_within = total([item for item in done if item["id"] in linked])
        done_extra = total([item for item in done if item["id"] not in linked])
        planned = sum(float(item["duration_min"] or 0) for item in plans)
        if load:
            # Existing activity load is exact; unlinked future plan load needs the planner's own model.
            from coach.planning import estimate_load, load_model
            model = load_model(source.settings.db_path, source.settings.default_user_id,
                               week + timedelta(days=7), source.settings)
            estimates = [estimate_load({"sport": item["sport"], "intent": item["intent"],
                                        "duration_min": item["duration_min"]}, model) for item in plans]
            planned = sum(estimates) if all(value is not None for value in estimates) else None
        rows.append({"Week": week.isoformat(), "Planned": round(planned, 1) if planned is not None else None,
                     "Done in plan": round(done_within, 1) if done_within is not None else None,
                     "Done beyond plan": round(done_extra, 1) if done_extra is not None else None})
    return ChartData(("Week", "Planned", "Done in plan", "Done beyond plan"), tuple(rows),
                     "Minutes" if not load else "Load; unmeasured plan sessions use the planner's existing estimate")


def intensity_share(source: DashboardSource, start: date, end: date, options: WidgetOptions) -> ChartData:
    sport = options.sport or "running"
    rows = []
    for week in _week_keys(start, end):
        chosen = [item for item in source.sessions if item["sport"] == sport and
                  week <= item["day"] < week + timedelta(days=7)]
        weighted = [(sum(item["zones"].get(z) or 0 for z in ("Z1", "Z2")),
                     sum(item["zones"].get(z) or 0 for z in ("Z3", "Z4", "Z5")),
                     item["observed_minutes"])
                    for item in chosen if item["zones"] and item["observed_minutes"]]
        if not weighted:
            continue
        duration = sum(minutes for _, _, minutes in weighted)
        low = sum(share * minutes for share, _, minutes in weighted) / duration
        high = sum(share * minutes for _, share, minutes in weighted) / duration
        rows.append({"Week": week.isoformat(), "Z1–Z2 %": round(low, 1), "Z3+ %": round(high, 1)})
    if options.moving_average:
        for index, row in enumerate(rows):
            row["4-week average %"] = round(mean(float(item["Z1–Z2 %"]) for item in rows[max(0, index - 3):index + 1]), 1)
    columns = ("Week", "Z1–Z2 %", "Z3+ %", "4-week average %") if options.moving_average else ("Week", "Z1–Z2 %", "Z3+ %")
    return ChartData(columns, tuple(rows), "Shares use observed HR-stream time; below-Z1 time is not shown.")


def _rolling_effort(points: tuple[tuple[float, float], ...], target: float) -> float | None:
    best = None
    left = 0
    for right, (distance, elapsed) in enumerate(points):
        while left < right and distance - points[left][0] >= target:
            previous_d, previous_t = points[left]
            pace = (elapsed - previous_t) / 60
            if pace > 0 and (best is None or pace < best):
                best = pace
            left += 1
    return best


def best_efforts(source: DashboardSource, start: date, end: date, options: WidgetOptions) -> ChartData:
    target = options.distance_km or 5
    rows = []
    for item in source.activities:
        if sport_category(item["type"], source.day) != "running" or not start <= date.fromisoformat(item["date"]) <= end:
            continue
        points = source.points.get(item["id"], ())
        best = _rolling_effort(points, target) if len(points) > 1 else None
        method = "rolling samples" if best else None
        if best is None and target == 1:
            valid = [float(lap["duration"]) for lap in source.laps.get(item["id"], ())
                     if lap["duration"] and lap["distance"] and .95 <= lap["distance"] <= 1.05]
            if valid:
                best, method = min(valid), "full-km lap"
        if best is None and target in (5, 10) and item["distance"] and abs(item["distance"] - target) <= target * .05:
            best, method = float(item["duration"]), "whole activity within 5%"
        if best is not None:
            rows.append({"Date": item["date"], "Time (min)": round(best, 2), "Method": method})
    return ChartData(("Date", "Time (min)", "Method"), tuple(rows),
                     "Measured from rolling samples, full-km laps (1 km), or whole activities within 5% (5/10 km).")


def pace_vs_hr_easy(source: DashboardSource, start: date, end: date, options: WidgetOptions) -> ChartData:
    by_id = {item["id"]: item for item in source.sessions}
    rows = []
    for item in source.activities:
        session = by_id.get(item["id"])
        if not session or session["sport"] != "running" or session["intent"] not in ("easy", "recovery"):
            continue
        if start <= date.fromisoformat(item["date"]) <= end and item["pace"] and item["avg_hr"]:
            rows.append({"Date": item["date"], "Pace (min/km)": round(float(item["pace"]), 2),
                         "Avg HR (bpm)": round(float(item["avg_hr"]))})
    return ChartData(("Date", "Pace (min/km)", "Avg HR (bpm)"), tuple(rows),
                     "Lower HR at the same pace = fitter. Recent points are emphasized.")


def _daily_recovery(source: DashboardSource, start: date, end: date) -> list[dict]:
    inputs = read_inputs(source.settings.db_path, source.settings.default_user_id, end,
                         source.settings.local_timezone, point_lookback_days=28)
    health_days = {date.fromisoformat(item["date"]) for item in source.health}
    result = []
    cursor = start
    while cursor <= end:
        if cursor in health_days:
            snapshot = build_daily_snapshot(inputs, cursor, source.settings.local_timezone,
                                            source.settings.sleep_goal_hours, source.settings.hr_zones)
            current = {key: value.value for key, value in snapshot.current_health}
            baseline = {(item.field, item.days): item.mean.value for item in snapshot.baselines}
            result.append({"Date": cursor.isoformat(), "Recovery": snapshot.readiness.score.value,
                           "Sleep (h)": current.get("sleep_duration"), "Resting HR (bpm)": current.get("resting_hr"),
                           "HRV (ms)": current.get("hrv"), "RHR usual": baseline.get(("resting_hr", 7)),
                           "HRV usual": baseline.get(("hrv", 28))})
        else:
            result.append({"Date": cursor.isoformat(), "Recovery": None, "Sleep (h)": None,
                           "Resting HR (bpm)": None, "HRV (ms)": None, "RHR usual": None, "HRV usual": None})
        cursor += timedelta(days=1)
    return result


def sleep_vs_recovery(source: DashboardSource, start: date, end: date, options: WidgetOptions) -> ChartData:
    rows = tuple({key: row[key] for key in ("Date", "Sleep (h)", "Recovery")}
                 for row in _daily_recovery(source, start, end) if row["Sleep (h)"] is not None and row["Recovery"] is not None)
    return ChartData(("Date", "Sleep (h)", "Recovery"), rows)


def weekly_load(source: DashboardSource, start: date, end: date, options: WidgetOptions) -> ChartData:
    rows = []
    for week in _week_keys(start, end):
        recorded = weekly_load_reference(list(source.reference_rows), week, limit=None)
        usual = usual_week(recorded)
        current = [item for item in source.reference_rows if week <= item[0] < week + timedelta(days=7)
                   and item[1] not in ("walking", "excluded", "mobility")]
        if not current:
            continue
        total = sum(item[2] or 0 for item in current) if all(item[2] is not None for item in current) else None
        rows.append({"Week": week.isoformat(), "% of usual": round(total / usual * 100, 1)
                     if total is not None and usual else None,
                     "Status": "baseline still building" if usual is None else "usual available"})
    return ChartData(("Week", "% of usual", "Status"), tuple(rows), "110% weekly limit")


def training_mix(source: DashboardSource, start: date, end: date, options: WidgetOptions) -> ChartData:
    rows = []
    for week in _week_keys(start, end):
        chosen = [item for item in source.sessions if week <= item["day"] < week + timedelta(days=7)
                  and item["sport"] not in ("excluded", "mobility")]
        if chosen:
            row: Row = {"Week": week.isoformat()}
            for sport in ("running", "volleyball", "football", "gym", "other"):
                row[sport.title() + " (min)"] = round(sum(item["duration"] or 0 for item in chosen
                                                               if item["sport"] == sport), 1)
            rows.append(row)
    return ChartData(("Week", "Running (min)", "Volleyball (min)", "Football (min)", "Gym (min)", "Other (min)"),
                     tuple(rows))


def recovery_trends(source: DashboardSource, start: date, end: date, options: WidgetOptions) -> ChartData:
    key = {"recovery": "Recovery", "resting_hr": "Resting HR (bpm)", "hrv": "HRV (ms)"}[
        options.recovery_metric or "recovery"]
    values = _daily_recovery(source, start, end)
    show_band = options.usual_range is not False
    previous = []
    if show_band:
        previous_end = start - timedelta(days=1)
        previous_start = previous_end - (end - start)
        previous = _daily_recovery(source, previous_start, previous_end)
    observed = [float(row[key]) for row in previous if row[key] is not None]
    usable = show_band and len(observed) >= (len(previous) + 1) // 2
    usual = mean(observed) if usable else None
    floor = MIN_MEANINGFUL_CHANGE.get({"resting_hr": "rhr"}.get(options.recovery_metric or "recovery",
                                                               options.recovery_metric or "recovery"), 3)
    variation = max(floor, pstdev(observed) if len(observed) > 1 else 0)
    rows = []
    for index, row in enumerate(values):
        item: Row = {"Date": row["Date"], key: round(row[key], 1) if row[key] is not None else None,
                     "Usual low": round(usual - variation, 1) if usual is not None else None,
                     "Usual high": round(usual + variation, 1) if usual is not None else None}
        if options.moving_average is not False:
            recent = [float(entry[key]) for entry in values[max(0, index - 6):index + 1]
                      if entry[key] is not None]
            item["7-day average"] = round(mean(recent), 1) if recent else None
        rows.append(item)
    columns = ("Date", key, "Usual low", "Usual high") + (("7-day average",) if options.moving_average is not False else ())
    note = ("Usual band: previous period average +/- normal day-to-day variation."
            if usable else "Not enough previous-period data for a usual band." if show_band else "")
    return ChartData(columns, tuple(rows), note)


REGISTRY = {
    item.id: item for item in (
        ChartDefinition("planned_vs_done", "Planned vs done", "Compare planned and completed training by week.",
                        planned_vs_done, ("measure",), "full", "stacked"),
        ChartDefinition("intensity_share", "Intensity share", "See easy and harder zone time each week.",
                        intensity_share, ("sport", "moving_average"), "half", "stacked",
                        supports_moving_average=True),
        ChartDefinition("best_efforts", "Best efforts", "Track measured 1K, 5K and 10K best efforts.",
                        best_efforts, ("distance_km",), "half", "line"),
        ChartDefinition("pace_vs_hr_easy", "Easy pace vs HR", "Compare pace and heart rate on easy runs.",
                        pace_vs_hr_easy, (), "half", "scatter"),
        ChartDefinition("sleep_vs_recovery", "Sleep vs Recovery", "Compare sleep with next-day Recovery.",
                        sleep_vs_recovery, (), "half", "scatter"),
        ChartDefinition("weekly_load", "Weekly load", "See weekly load as a percent of usual.",
                        weekly_load, (), "half", "bar"),
        ChartDefinition("training_mix", "Training mix", "See duration by sport each week.",
                        training_mix, (), "half", "stacked"),
        ChartDefinition("recovery_trends", "Recovery trends", "Follow Recovery, resting HR or HRV.",
                        recovery_trends, ("recovery_metric", "moving_average", "usual_range"), "half", "line",
                        supports_usual_range=True, supports_moving_average=True),
    )
}
