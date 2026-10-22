"""Read-only metrics JSON and optional seven-day legacy comparison."""

import argparse
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import date, timedelta
from math import isfinite
from pathlib import Path

from metrics.reader import get_daily_snapshot, local_day


def compare_legacy(database: Path, user_id: int, as_of: date, timezone: str, sleep_goal_hours: float) -> list[dict]:
    import pandas as pd

    from analytics.performance import readiness_score, training_load_series

    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        activities = pd.read_sql_query("SELECT date,type,distance,duration,avg_hr,aerobic_effect,anaerobic_effect FROM activities WHERE user_id=?", connection, params=(user_id,))
        health = pd.read_sql_query("SELECT date,resting_hr,hrv,sleep_duration,sleep_score,body_battery,recovery_time FROM health_metrics WHERE user_id=?", connection, params=(user_id,))
        profile = connection.execute("SELECT max_hr FROM users WHERE id=?", (user_id,)).fetchone()
    if profile is None:
        raise ValueError(f"User {user_id} does not exist")
    for frame in (activities, health):
        frame["date"] = pd.to_datetime([local_day(value, timezone, as_of) for value in frame["date"]])
        for column in frame.columns.difference(["date", "type"]):
            frame[column] = pd.to_numeric(frame[column], errors="coerce").astype(float)
    rows = []
    for offset in range(6, -1, -1):
        day = as_of - timedelta(days=offset)
        runs = activities[activities.date <= pd.Timestamp(day)]
        recovery = health[health.date <= pd.Timestamp(day)]
        old_load = training_load_series(runs)
        old_acute = float(old_load[old_load.date >= pd.Timestamp(day - timedelta(days=6))].training_load.sum())
        new = get_daily_snapshot(day, database=database, user_id=user_id, timezone=timezone, sleep_goal_hours=sleep_goal_hours)
        old_readiness = readiness_score(runs, recovery, profile[0])["score"]
        rows.append({"date": day.isoformat(), "old_readiness": old_readiness if isfinite(old_readiness) else None,
                     "new_readiness": new.readiness.score.value, "old_7d_load_arbitrary_units": old_acute,
                     "new_7d_load_trimp": new.load.acute.value, "new_load_ratio": new.load.ratio.value,
                     "acute_observed_days": new.load.acute.provenance.n_days,
                     "chronic_observed_days": new.load.chronic.provenance.n_days})
    return rows


def main() -> None:
    from config import get_settings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    parser.add_argument("--db", type=Path)
    parser.add_argument("--user-id", type=int)
    parser.add_argument("--compare-last-7", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    database = args.db if args.db is not None else settings.db_path
    user_id = args.user_id if args.user_id is not None else settings.default_user_id
    result = {"snapshot": asdict(get_daily_snapshot(args.date, database=database, user_id=user_id))}
    if args.compare_last_7:
        result["comparison"] = compare_legacy(database, user_id, args.date, settings.local_timezone, settings.sleep_goal_hours)
        result["comparison_note"] = "Old load is an arbitrary-unit heuristic, not TRIMP. Old readiness uses legacy defaults and latest-record windows."
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
