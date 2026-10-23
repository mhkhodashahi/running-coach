"""Athlete-owned weekly plans and individually approved coach suggestions."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from coach.decision import REST_READINESS, TEAM_SPORTS
from coach.plan import (
    MAX_WEEKLY_LOAD_INCREASE,
    draft_week,
    interpret_revision,
    make_session,
    monday,
    projected_plan_load,
)
from config import Settings, get_settings
from metrics import get_daily_snapshot
from metrics.load import banister_trimp
from metrics.sports import RECOMMENDABLE_SPORTS, sport_category
from services.hr_zones import heart_rate_zone_bounds

MAX_PROPOSAL_CHANGES = 7
MAX_PROPOSALS = 12


@contextmanager
def _connection(settings: Settings) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(settings.db_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat()


def _week(day: date) -> date:
    if day != monday(day):
        raise ValueError("Choose a Monday as the week start")
    return day


def _plan(connection: sqlite3.Connection, user_id: int, start: date, *, create: bool = False) -> sqlite3.Row | None:
    row = connection.execute("SELECT * FROM weekly_plans WHERE user_id=? AND week_start=?",
                             (user_id, start.isoformat())).fetchone()
    if row is None and create:
        connection.execute("INSERT INTO weekly_plans(user_id,week_start,revision,sessions_json,updated_at) "
                           "VALUES(?,?,0,'{}',?)", (user_id, start.isoformat(), _now()))
        row = connection.execute("SELECT * FROM weekly_plans WHERE user_id=? AND week_start=?",
                                 (user_id, start.isoformat())).fetchone()
    return row


def _plan_view(row: sqlite3.Row | None, start: date) -> dict[str, Any]:
    return {"week_start": start.isoformat(), "revision": row["revision"] if row else 0,
            "sessions": json.loads(row["sessions_json"]) if row else {}}


def get_weekly_plan(start: date, *, settings: Settings | None = None,
                    user_id: int | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    start = _week(start)
    with _connection(settings) as connection:
        row = _plan(connection, user_id or settings.default_user_id, start)
    return _plan_view(row, start)


def scheduled_team_sports(day: date, *, settings: Settings | None = None,
                          user_id: int | None = None) -> tuple[str, ...]:
    plan = get_weekly_plan(monday(day), settings=settings, user_id=user_id)
    session = plan["sessions"].get(day.isoformat())
    return (session["sport"],) if session and session["sport"] in ("football", "volleyball") else ()


def _z2_cap(settings: Settings, user: sqlite3.Row) -> int | None:
    if len(settings.hr_zones) >= 2:
        return settings.hr_zones[1][2]
    max_hr = user["max_hr"] or (220 - user["age"] if user["age"] else None)
    return int(heart_rate_zone_bounds(int(max_hr))[1][2] - 1e-9) if max_hr else None


def _facts(start: date, training_days: int, prior_minutes: int,
           prior_load: float, load_budget: float) -> list[dict[str, str]]:
    return [
        {"id": "PLAN_WEEK_START", "metric": "Week start", "display": start.isoformat(),
         "source": "weekly_plans.week_start"},
        {"id": "TRAINING_DAYS", "metric": "Preferred training days", "display": f"{training_days} days/week",
         "source": "users.training_days_per_week"},
        {"id": "PRIOR_WEEK_MINUTES", "metric": "Previous week training time", "display": f"{prior_minutes} min",
         "source": "activities.date,type,duration"},
        {"id": "PRIOR_WEEK_LOAD", "metric": "Previous week load", "display": f"{prior_load:.1f} TRIMP",
         "source": "metrics_snapshot.sessions.load.value"},
        {"id": "MAX_PLAN_LOAD", "metric": "Maximum projected plan load", "display": f"{load_budget:.1f} TRIMP",
         "source": "metrics_snapshot.sessions.load.value + coach.plan.MAX_WEEKLY_LOAD_INCREASE"},
    ]


def _load_context(settings: Settings, user_id: int, start: date,
                  as_of: date, z2_cap: int | None) -> tuple[float, dict[str, float], float]:
    end = min(as_of, start - timedelta(days=1))
    snapshot = get_daily_snapshot(end, database=settings.db_path, user_id=user_id,
                                  timezone=settings.local_timezone, sleep_goal_hours=settings.sleep_goal_hours)
    prior = [item for item in snapshot.sessions if (start - timedelta(days=7)).isoformat() <= item.day <
             start.isoformat()]
    if not prior or any(item.load.value is None for item in prior):
        raise ValueError("Recent session load is missing; no weekly load increase can be checked")
    prior_load = sum(item.load.value for item in prior)
    if prior_load <= 0:
        raise ValueError("Recent session load is missing; no weekly load increase can be checked")
    with _connection(settings) as connection:
        user = connection.execute("SELECT max_hr,age FROM users WHERE id=?", (user_id,)).fetchone()
        health = connection.execute("SELECT resting_hr FROM health_metrics WHERE user_id=? AND date<=? "
                                    "AND resting_hr IS NOT NULL ORDER BY date DESC LIMIT 1",
                                    (user_id, end.isoformat())).fetchone()
        durations = {row["id"]: row["duration"] for row in connection.execute(
            "SELECT id,duration FROM activities WHERE user_id=? AND date>=? AND date<=?",
            (user_id, (end - timedelta(days=27)).isoformat(), end.isoformat()))}
    max_hr = user["max_hr"] or (220 - user["age"] if user["age"] else None) if user else None
    rates = {}
    if z2_cap is not None and health and max_hr:
        running = banister_trimp(1, z2_cap, health["resting_hr"], max_hr, end)
        if running is not None and running > 0:
            rates["running"] = running
    gym_rates = [item.load.value / durations[item.activity_id] for item in snapshot.sessions
                 if item.sport == "gym" and item.load.value is not None and durations.get(item.activity_id, 0) > 0]
    if gym_rates:
        rates["gym"] = max(gym_rates) * 1.25
    return prior_load * MAX_WEEKLY_LOAD_INCREASE, rates, prior_load


def _create_proposal(connection: sqlite3.Connection, user_id: int, plan: sqlite3.Row,
                     facts: list[dict[str, str]], changes: list[tuple[date, dict[str, Any] | None,
                                                                     str, tuple[str, ...]]]) -> int:
    if not 1 <= len(changes) <= MAX_PROPOSAL_CHANGES:
        raise ValueError("A proposal needs 1-7 changes")
    known = {fact["id"] for fact in facts}
    start = date.fromisoformat(plan["week_start"])
    sessions = json.loads(plan["sessions_json"])
    for day, session, reason, fact_ids in changes:
        if not start <= day < start + timedelta(days=7) or not reason.strip() or not fact_ids or set(fact_ids) - known:
            raise ValueError("Every change needs a valid day, reason and known fact IDs")
        if sessions.get(day.isoformat(), {}).get("fixed"):
            raise ValueError("A fixed athlete commitment cannot be changed by the coach")
        if session is not None and session.get("fixed"):
            raise ValueError("Coach proposals cannot create fixed commitments")
    cursor = connection.execute(
        "INSERT INTO coach_plan_proposals(user_id,plan_id,base_revision,status,facts_json,created_at) "
        "VALUES(?,?,?,'open',?,?)",
        (user_id, plan["id"], plan["revision"], json.dumps(facts), _now()),
    )
    proposal_id = cursor.lastrowid
    for day, session, reason, fact_ids in changes:
        connection.execute("INSERT INTO coach_plan_changes(proposal_id,day,session_json,reason,fact_ids_json,status) "
                           "VALUES(?,?,?,?,?,'pending')",
                           (proposal_id, day.isoformat(), json.dumps(session), reason, json.dumps(fact_ids)))
    return proposal_id


def propose_week(start: date, *, settings: Settings | None = None, user_id: int | None = None,
                 today: date | None = None) -> dict[str, Any]:
    """Suggest only easy additions within last week's time; never change the plan."""
    settings = settings or get_settings()
    user_id = user_id or settings.default_user_id
    start = _week(start)
    today = today or datetime.now(ZoneInfo(settings.local_timezone)).date()
    with _connection(settings) as connection:
        user = connection.execute("SELECT training_days_per_week,max_hr,age FROM users WHERE id=?",
                                  (user_id,)).fetchone()
        if user is None:
            raise ValueError("Athlete profile not found")
        recent = connection.execute("SELECT date,type,duration FROM activities WHERE user_id=? "
                                    "AND date>=? AND date<?", (user_id, (start - timedelta(days=7)).isoformat(),
                                                                start.isoformat())).fetchall()
        prior_minutes = max(0, int(sum(row["duration"] for row in recent if row["duration"] is not None and
                                       sport_category(row["type"], date.fromisoformat(row["date"]))
                                       in RECOMMENDABLE_SPORTS)))
        training_days = user["training_days_per_week"] if user["training_days_per_week"] is not None else 3
        z2_cap = _z2_cap(settings, user)
    load_budget, rates, prior_load = _load_context(settings, user_id, start, today, z2_cap)
    snapshot = get_daily_snapshot(today, database=settings.db_path, user_id=user_id,
                                  timezone=settings.local_timezone, sleep_goal_hours=settings.sleep_goal_hours)
    with _connection(settings) as connection:
        connection.execute("BEGIN IMMEDIATE")
        plan = _plan(connection, user_id, start, create=True)
        assert plan is not None
        existing = json.loads(plan["sessions_json"])
        readiness = snapshot.readiness.score.value
        rest_today = (snapshot.readiness.illness_flag.value is True or
                      readiness is not None and readiness < REST_READINESS)
        suggestions = draft_week(start, today, training_days, prior_minutes, existing, z2_cap,
                                 rest_today=rest_today,
                                 load_budget=load_budget, load_rates=rates)
        facts = _facts(start, training_days, prior_minutes, prior_load, load_budget)
        reason = (f"I suggest easy work within your {facts[1]['display']} target and below last week's "
                  f"{facts[2]['display']} of training time. Prior load was {facts[3]['display']}; "
                  f"projected load stays below {facts[4]['display']}.")
        changes = [(day, session, reason, ("TRAINING_DAYS", "PRIOR_WEEK_MINUTES",
                                          "PRIOR_WEEK_LOAD", "MAX_PLAN_LOAD"))
                   for day, session in suggestions]
        if not changes:
            raise ValueError("No safe new sessions to suggest. Check recent training data or current plan.")
        proposal_id = _create_proposal(connection, user_id, plan, facts, changes)
    return get_proposal(proposal_id, settings=settings, user_id=user_id)


def _proposal_view(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    plan = connection.execute("SELECT revision,week_start FROM weekly_plans WHERE id=?", (row["plan_id"],)).fetchone()
    status = "stale" if row["status"] == "open" and row["base_revision"] != plan["revision"] else row["status"]
    changes = connection.execute("SELECT id,day,session_json,reason,fact_ids_json,status FROM coach_plan_changes "
                                 "WHERE proposal_id=? ORDER BY id", (row["id"],)).fetchall()
    undone = {item[0] for item in connection.execute(
        "SELECT u.change_id FROM coach_plan_undo u JOIN coach_plan_changes c ON c.id=u.change_id "
        "WHERE c.proposal_id=? AND u.undone_at IS NOT NULL", (row["id"],))}
    return {"id": row["id"], "week_start": plan["week_start"], "base_revision": row["base_revision"],
            "status": status, "created_at": row["created_at"], "facts": json.loads(row["facts_json"]),
            "changes": [{"id": item["id"], "day": item["day"], "session": json.loads(item["session_json"]),
                         "reason": item["reason"], "fact_ids": json.loads(item["fact_ids_json"]),
                         "undone": item["id"] in undone,
                         "status": "stale" if status == "stale" and item["status"] == "pending" else item["status"]}
                        for item in changes]}


def get_proposal(proposal_id: int, *, settings: Settings | None = None,
                 user_id: int | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    with _connection(settings) as connection:
        row = connection.execute("SELECT * FROM coach_plan_proposals WHERE id=? AND user_id=?",
                                 (proposal_id, user_id or settings.default_user_id)).fetchone()
        if row is None:
            raise ValueError("Proposal not found for this athlete")
        return _proposal_view(connection, row)


def list_proposals(start: date, *, settings: Settings | None = None,
                   user_id: int | None = None) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    start = _week(start)
    with _connection(settings) as connection:
        rows = connection.execute("SELECT p.* FROM coach_plan_proposals p JOIN weekly_plans w ON w.id=p.plan_id "
                                  "WHERE p.user_id=? AND w.week_start=? ORDER BY p.id DESC LIMIT ?",
                                  (user_id or settings.default_user_id, start.isoformat(), MAX_PROPOSALS)).fetchall()
        return [_proposal_view(connection, row) for row in rows]


def _stale_other_proposals(connection: sqlite3.Connection, plan_id: int, keep_id: int | None = None) -> None:
    clause = " AND id!=?" if keep_id is not None else ""
    args = (plan_id, keep_id) if keep_id is not None else (plan_id,)
    connection.execute(f"UPDATE coach_plan_changes SET status='stale' WHERE status='pending' AND proposal_id IN "
                       f"(SELECT id FROM coach_plan_proposals WHERE plan_id=? AND status='open'{clause})", args)
    connection.execute(f"UPDATE coach_plan_proposals SET status='stale' WHERE plan_id=? AND status='open'{clause}", args)


def accept_change(change_id: int, *, settings: Settings | None = None,
                  user_id: int | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    user_id = user_id or settings.default_user_id
    with _connection(settings) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT c.*,p.plan_id,p.base_revision,p.status AS proposal_status,w.revision," 
                                 "w.sessions_json,w.week_start FROM coach_plan_changes c "
                                 "JOIN coach_plan_proposals p ON p.id=c.proposal_id "
                                 "JOIN weekly_plans w ON w.id=p.plan_id "
                                 "WHERE c.id=? AND p.user_id=? AND w.user_id=?",
                                 (change_id, user_id, user_id)).fetchone()
        if row is None:
            raise ValueError("Change not found for this athlete")
        if row["status"] != "pending" or row["proposal_status"] != "open":
            raise ValueError("This change is no longer pending")
        if row["revision"] != row["base_revision"]:
            _stale_other_proposals(connection, row["plan_id"])
            connection.commit()
            raise ValueError("Proposal is stale because the plan changed. Request a fresh proposal.")
        sessions = json.loads(row["sessions_json"])
        if sessions.get(row["day"], {}).get("fixed"):
            raise ValueError("A fixed athlete commitment cannot be changed by the coach")
        proposed = json.loads(row["session_json"])
        if proposed is None:
            sessions.pop(row["day"], None)
        else:
            today = datetime.now(ZoneInfo(settings.local_timezone)).date()
            if row["day"] == today.isoformat():
                snapshot = get_daily_snapshot(today, database=settings.db_path, user_id=user_id,
                                              timezone=settings.local_timezone,
                                              sleep_goal_hours=settings.sleep_goal_hours)
                readiness = snapshot.readiness.score.value
                if (snapshot.readiness.illness_flag.value is True or
                        readiness is not None and readiness < REST_READINESS):
                    raise ValueError("Today's recovery calls for rest; request a fresh proposal")
            sessions[row["day"]] = proposed
            user = connection.execute("SELECT max_hr,age FROM users WHERE id=?", (user_id,)).fetchone()
            budget, rates, _ = _load_context(settings, user_id, date.fromisoformat(row["week_start"]),
                                             datetime.now(ZoneInfo(settings.local_timezone)).date(),
                                             _z2_cap(settings, user))
            estimate = projected_plan_load(sessions, rates)
            if estimate is None or estimate > budget + 1e-6:
                raise ValueError("Projected weekly load exceeds the 10% cap or cannot be verified")
        revision = row["revision"] + 1
        after_json = json.dumps(sessions, sort_keys=True)
        connection.execute("INSERT INTO coach_plan_undo(user_id,plan_id,change_id,before_json,after_json," 
                           "after_revision,expected_revision,created_at) VALUES(?,?,?,?,?,?,?,?)",
                           (user_id, row["plan_id"], change_id, row["sessions_json"], after_json,
                            revision, revision, _now()))
        connection.execute("UPDATE weekly_plans SET sessions_json=?,revision=?,updated_at=? WHERE id=?",
                           (after_json, revision, _now(), row["plan_id"]))
        connection.execute("UPDATE coach_plan_changes SET status='accepted' WHERE id=?", (change_id,))
        connection.execute("UPDATE coach_plan_proposals SET base_revision=? WHERE id=?",
                           (revision, row["proposal_id"]))
        pending = connection.execute("SELECT COUNT(*) FROM coach_plan_changes WHERE proposal_id=? AND status='pending'",
                                     (row["proposal_id"],)).fetchone()[0]
        if not pending:
            connection.execute("UPDATE coach_plan_proposals SET status='complete' WHERE id=?",
                               (row["proposal_id"],))
        _stale_other_proposals(connection, row["plan_id"], row["proposal_id"])
        return {"week_start": row["week_start"], "revision": revision, "sessions": sessions}


def reject_change(change_id: int, *, settings: Settings | None = None,
                  user_id: int | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    user_id = user_id or settings.default_user_id
    with _connection(settings) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT c.status,c.proposal_id,p.status AS proposal_status,p.base_revision," 
                                 "w.revision,w.id AS plan_id FROM coach_plan_changes c "
                                 "JOIN coach_plan_proposals p ON p.id=c.proposal_id "
                                 "JOIN weekly_plans w ON w.id=p.plan_id WHERE c.id=? AND p.user_id=?",
                                 (change_id, user_id)).fetchone()
        if row is None:
            raise ValueError("Change not found for this athlete")
        if row["status"] != "pending" or row["proposal_status"] != "open":
            raise ValueError("This change is no longer pending")
        if row["revision"] != row["base_revision"]:
            _stale_other_proposals(connection, row["plan_id"])
            connection.commit()
            raise ValueError("Proposal is stale because the plan changed. Request a fresh proposal.")
        connection.execute("UPDATE coach_plan_changes SET status='rejected' WHERE id=?", (change_id,))
        pending = connection.execute("SELECT COUNT(*) FROM coach_plan_changes WHERE proposal_id=? AND status='pending'",
                                     (row["proposal_id"],)).fetchone()[0]
        if not pending:
            connection.execute("UPDATE coach_plan_proposals SET status='complete' WHERE id=?",
                               (row["proposal_id"],))
    return get_proposal(row["proposal_id"], settings=settings, user_id=user_id)


def set_fixed_commitment(day: date, sport: str | None, *, settings: Settings | None = None,
                         user_id: int | None = None, duration_min: int = 60) -> dict[str, Any]:
    """A direct athlete action, never a coach proposal or logged-activity edit."""
    settings = settings or get_settings()
    user_id = user_id or settings.default_user_id
    start = monday(day)
    if sport is not None and sport not in ("football", "volleyball"):
        raise ValueError("Fixed team commitment must be football or volleyball")
    with _connection(settings) as connection:
        connection.execute("BEGIN IMMEDIATE")
        plan = _plan(connection, user_id, start, create=True)
        assert plan is not None
        sessions = json.loads(plan["sessions_json"])
        if sport is None:
            if not sessions.get(day.isoformat(), {}).get("fixed"):
                raise ValueError("No fixed commitment on this day")
            sessions.pop(day.isoformat())
        else:
            sessions[day.isoformat()] = make_session(sport, duration_min=duration_min, fixed=True)
        revision = plan["revision"] + 1
        connection.execute("UPDATE weekly_plans SET sessions_json=?,revision=?,updated_at=? WHERE id=?",
                           (json.dumps(sessions, sort_keys=True), revision, _now(), plan["id"]))
        _stale_other_proposals(connection, plan["id"])
    return {"week_start": start.isoformat(), "revision": revision, "sessions": sessions}


def revise_proposal(proposal_id: int, request: str, *, settings: Settings | None = None,
                    user_id: int | None = None) -> dict[str, Any]:
    """Plain words create a fresh proposal; they never apply the requested change."""
    settings = settings or get_settings()
    user_id = user_id or settings.default_user_id
    if not 1 <= len(request.strip()) <= 300:
        raise ValueError("Describe one day-level revision in 300 characters or fewer")
    with _connection(settings) as connection:
        row = connection.execute("SELECT p.*,w.week_start,w.revision FROM coach_plan_proposals p "
                                 "JOIN weekly_plans w ON w.id=p.plan_id WHERE p.id=? AND p.user_id=?",
                                 (proposal_id, user_id)).fetchone()
        if row is None:
            raise ValueError("Proposal not found for this athlete")
        if row["status"] != "open" or row["base_revision"] != row["revision"]:
            raise ValueError("Proposal is stale or complete. Request fresh weekly suggestions.")
        user = connection.execute("SELECT max_hr,age FROM users WHERE id=?", (user_id,)).fetchone()
        day, session = interpret_revision(request, date.fromisoformat(row["week_start"]), _z2_cap(settings, user))
        if session is not None and session["sport"] in TEAM_SPORTS:
            raise ValueError("Use fixed team training for football or volleyball; team load cannot be bounded yet")
    facts = [{"id": "PLAN_WEEK_START", "metric": "Week start", "display": row["week_start"],
              "source": "weekly_plans.week_start"},
             {"id": "ATHLETE_REQUEST", "metric": "Revision source", "display": "athlete request",
              "source": "athlete_input"}]
    reason = (f"You asked for {day:%A} to be " + (f"{session['sport']} ({session['intent']})" if session else "rest")
              + f" in the week of {row['week_start']}.")
    with _connection(settings) as connection:
        connection.execute("BEGIN IMMEDIATE")
        plan = _plan(connection, user_id, date.fromisoformat(row["week_start"]))
        assert plan is not None
        current = connection.execute("SELECT status,base_revision FROM coach_plan_proposals WHERE id=? AND user_id=?",
                                     (proposal_id, user_id)).fetchone()
        if current["status"] != "open" or plan["revision"] != current["base_revision"]:
            raise ValueError("Plan changed during revision. Request a fresh proposal.")
        if session is not None:
            user = connection.execute("SELECT max_hr,age FROM users WHERE id=?", (user_id,)).fetchone()
            budget, rates, _ = _load_context(settings, user_id, date.fromisoformat(row["week_start"]),
                                             datetime.now(ZoneInfo(settings.local_timezone)).date(),
                                             _z2_cap(settings, user))
            candidate = json.loads(plan["sessions_json"])
            candidate[day.isoformat()] = session
            estimate = projected_plan_load(candidate, rates)
            if estimate is None or estimate > budget + 1e-6:
                raise ValueError("Projected weekly load exceeds the 10% cap or cannot be verified")
        new_id = _create_proposal(connection, user_id, plan, facts,
                                  [(day, session, reason, ("ATHLETE_REQUEST", "PLAN_WEEK_START"))])
        connection.execute("UPDATE coach_plan_changes SET status='stale' WHERE proposal_id=? AND status='pending'",
                           (proposal_id,))
        connection.execute("UPDATE coach_plan_proposals SET status='stale' WHERE id=?", (proposal_id,))
    return get_proposal(new_id, settings=settings, user_id=user_id)


def undo_last_coach_change(start: date, *, settings: Settings | None = None,
                           user_id: int | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    user_id = user_id or settings.default_user_id
    start = _week(start)
    with _connection(settings) as connection:
        connection.execute("BEGIN IMMEDIATE")
        plan = _plan(connection, user_id, start)
        if plan is None:
            raise ValueError("No weekly plan to undo")
        undo = connection.execute("SELECT * FROM coach_plan_undo WHERE plan_id=? AND user_id=? "
                                  "AND undone_at IS NULL ORDER BY id DESC LIMIT 1", (plan["id"], user_id)).fetchone()
        if undo is None:
            raise ValueError("No coach change to undo")
        current = json.loads(plan["sessions_json"])
        before = json.loads(undo["before_json"])
        after = json.loads(undo["after_json"])
        change = connection.execute("SELECT day FROM coach_plan_changes WHERE id=?", (undo["change_id"],)).fetchone()
        day = change["day"]
        if current.get(day) != after.get(day):
            raise ValueError("This day was edited after coach approval; undo will not overwrite your change")
        if plan["revision"] == undo["expected_revision"]:
            restored_json = undo["before_json"]
        else:
            if day in before:
                current[day] = before[day]
            else:
                current.pop(day, None)
            restored_json = json.dumps(current, sort_keys=True)
        revision = plan["revision"] + 1
        connection.execute("UPDATE weekly_plans SET sessions_json=?,revision=?,updated_at=? WHERE id=?",
                           (restored_json, revision, _now(), plan["id"]))
        connection.execute("UPDATE coach_plan_undo SET undone_at=? WHERE id=?", (_now(), undo["id"]))
        previous = connection.execute("SELECT id FROM coach_plan_undo WHERE plan_id=? AND user_id=? "
                                      "AND undone_at IS NULL ORDER BY id DESC LIMIT 1",
                                      (plan["id"], user_id)).fetchone()
        if previous:
            connection.execute("UPDATE coach_plan_undo SET expected_revision=? WHERE id=?",
                               (revision, previous["id"]))
        _stale_other_proposals(connection, plan["id"])
    return {"week_start": start.isoformat(), "revision": revision, "sessions": json.loads(restored_json)}
