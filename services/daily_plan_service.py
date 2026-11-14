"""Create a proposal for a daily decision conflict; never apply a change."""

from __future__ import annotations

from datetime import date
from typing import Any

from coach.proposals import create_proposal, get_week, materialize_week, monday
from coach.week_rules import is_hard
from config import Settings, get_settings
from db.repositories.planning import PlanningRepository
from db.session import session_scope


def propose_daily_conflict(day: date, intensity: str, decision_facts: list[dict[str, str]], *,
                           settings: Settings | None = None, user_id: int | None = None) -> list[dict[str, Any]]:
    """Suggest a lighter plan when today's code decision and plan disagree."""
    settings = settings or get_settings()
    user_id = user_id or settings.default_user_id
    if intensity == "hard":
        return []
    materialize_week(settings.db_path, user_id, monday(day))
    week = get_week(settings.db_path, user_id, monday(day))
    facts = [fact for fact in decision_facts if fact["id"] in
             ("READINESS", "WEEKLY_LOAD", "WEEKLY_LIMIT", "ILLNESS_FLAG")]
    if not facts:
        return []
    with session_scope(f"sqlite:///{settings.db_path.resolve()}") as session:
        exists = PlanningRepository(session).has_daily_conflict_proposal(
            user_id, week["version"], f"Review today's session ({day.isoformat()})"
        )
    if exists:
        return []
    proposals = []
    for planned in week["sessions"]:
        if planned["date"] != day.isoformat() or planned["status"] != "planned" or planned["id"] is None:
            continue
        if intensity != "rest" and (intensity != "easy" or not is_hard(planned)):
            continue
        item = {key: planned.get(key) for key in ("id", "date", "sport", "intent", "duration_min",
                                                  "hr_cap_bpm", "notes", "status")}
        if intensity == "rest":
            item["status"] = "skipped"
            reason = "Today's recovery decision suggests skipping this session."
        else:
            item["intent"] = "skills only" if item["sport"] in ("football", "volleyball") else (
                "light" if item["sport"] == "gym" else "easy")
            reason = "Today's decision calls for a lighter session."
        proposals.append(create_proposal(settings.db_path, user_id, "change",
                                         f"Review today's session ({day.isoformat()})", facts,
                                         [{"change_type": "modify", "session": item,
                                           "reason": reason, "fact_ids": [facts[0]["id"]]}],
                                         base_version=week["version"]))
    return proposals
