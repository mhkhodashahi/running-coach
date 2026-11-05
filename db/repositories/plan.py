"""Persistence operations for planned-session workout state."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


class PlanRepository:
    """User-scoped plan reads and atomic workout updates."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def version(self, user_id: int) -> int:
        value = self._session.execute(
            text("SELECT version FROM plan_versions WHERE user_id=:user_id"),
            {"user_id": user_id},
        ).scalar_one_or_none()
        return int(value or 0)

    def bump_version(self, user_id: int) -> int:
        self._session.execute(
            text("INSERT INTO plan_versions(user_id,version) VALUES(:user_id,1) "
                 "ON CONFLICT(user_id) DO UPDATE SET version=version+1"),
            {"user_id": user_id},
        )
        return self.version(user_id)

    def week_sessions(self, user_id: int, start: date) -> list[dict[str, Any]]:
        end = start + timedelta(days=7)
        return self._rows("SELECT * FROM plan_sessions WHERE user_id=:user_id AND date>=:start "
                          "AND date<:end ORDER BY date,id",
                          {"user_id": user_id, "start": start.isoformat(), "end": end.isoformat()})

    def week_mobility_sessions(self, user_id: int, start: date) -> list[dict[str, Any]]:
        end = start + timedelta(days=7)
        return self._rows("SELECT * FROM plan_mobility_sessions WHERE user_id=:user_id AND date>=:start "
                          "AND date<:end ORDER BY date,id",
                          {"user_id": user_id, "start": start.isoformat(), "end": end.isoformat()})

    def fixed_commitments(self, user_id: int, *, active_only: bool = False) -> list[dict[str, Any]]:
        active = " AND active=1" if active_only else ""
        return self._rows(f"SELECT * FROM fixed_commitments WHERE user_id=:user_id{active} "
                          "ORDER BY weekday,start_time,id", {"user_id": user_id})

    def protected_habits(self, user_id: int, *, active_only: bool = False) -> list[dict[str, Any]]:
        active = " AND active=1" if active_only else ""
        return self._rows(f"SELECT * FROM protected_habits WHERE user_id=:user_id{active} ORDER BY id",
                          {"user_id": user_id})

    def week_activities(self, user_id: int, start: date) -> list[dict[str, Any]]:
        end = start + timedelta(days=7)
        return self._rows("SELECT id,date,type FROM activities WHERE user_id=:user_id AND date>=:start "
                          "AND date<:end ORDER BY date,id",
                          {"user_id": user_id, "start": start.isoformat(), "end": end.isoformat()})

    def scheduled_team_sports(self, user_id: int, day: date) -> tuple[str, ...]:
        fixed = self._rows(
            "SELECT f.sport FROM fixed_commitments f WHERE f.user_id=:user_id AND f.weekday=:weekday "
            "AND f.active=1 AND NOT EXISTS (SELECT 1 FROM plan_sessions p WHERE p.user_id=f.user_id "
            "AND p.fixed_commitment_id=f.id AND p.date=:day AND p.status='skipped')",
            {"user_id": user_id, "weekday": day.weekday(), "day": day.isoformat()},
        )
        planned = self._rows("SELECT sport FROM plan_sessions WHERE user_id=:user_id AND date=:day "
                             "AND sport IN ('football','volleyball') AND status='planned'",
                             {"user_id": user_id, "day": day.isoformat()})
        return tuple(dict.fromkeys(row["sport"] for row in (*fixed, *planned)))

    def protected_habit_counts(self, user_id: int) -> list[dict[str, Any]]:
        return self._rows("SELECT id,per_week FROM protected_habits WHERE user_id=:user_id AND active=1",
                          {"user_id": user_id})

    def insert_protected_habit(self, user_id: int, sport: str, intent: str, duration_min: int,
                               per_week: int, active: bool) -> int:
        result = self._session.execute(
            text("INSERT INTO protected_habits(user_id,sport,intent,duration_min,per_week,active) "
                 "VALUES(:user_id,:sport,:intent,:duration,:per_week,:active)"),
            {"user_id": user_id, "sport": sport, "intent": intent, "duration": duration_min,
             "per_week": per_week, "active": int(active)},
        )
        return int(result.lastrowid or 0)

    def update_protected_habit(self, user_id: int, habit_id: int, sport: str, intent: str,
                               duration_min: int, per_week: int, active: bool) -> bool:
        result = self._session.execute(
            text("UPDATE protected_habits SET sport=:sport,intent=:intent,duration_min=:duration,"
                 "per_week=:per_week,active=:active WHERE id=:habit_id AND user_id=:user_id"),
            {"user_id": user_id, "habit_id": habit_id, "sport": sport, "intent": intent,
             "duration": duration_min, "per_week": per_week, "active": int(active)},
        )
        return result.rowcount == 1

    def insert_fixed_commitment(self, user_id: int, weekday: int, start_time: str, sport: str,
                                kind: str, duration_min: int, active: bool) -> int:
        result = self._session.execute(
            text("INSERT INTO fixed_commitments(user_id,weekday,start_time,sport,kind,typical_duration_min,active) "
                 "VALUES(:user_id,:weekday,:start_time,:sport,:kind,:duration,:active)"),
            {"user_id": user_id, "weekday": weekday, "start_time": start_time, "sport": sport,
             "kind": kind, "duration": duration_min, "active": int(active)},
        )
        return int(result.lastrowid or 0)

    def fixed_commitment(self, user_id: int, commitment_id: int) -> dict[str, Any] | None:
        return self._one("SELECT active FROM fixed_commitments WHERE id=:id AND user_id=:user_id",
                         {"id": commitment_id, "user_id": user_id})

    def update_fixed_commitment(self, user_id: int, commitment_id: int, weekday: int,
                                start_time: str, sport: str, kind: str, duration_min: int,
                                active: bool) -> bool:
        result = self._session.execute(
            text("UPDATE fixed_commitments SET weekday=:weekday,start_time=:start_time,sport=:sport,"
                 "kind=:kind,typical_duration_min=:duration,active=:active "
                 "WHERE id=:id AND user_id=:user_id"),
            {"id": commitment_id, "user_id": user_id, "weekday": weekday, "start_time": start_time,
             "sport": sport, "kind": kind, "duration": duration_min, "active": int(active)},
        )
        return result.rowcount == 1

    def commitment_sessions(self, user_id: int, commitment_id: int) -> list[dict[str, Any]]:
        return self._rows("SELECT id,date,status FROM plan_sessions WHERE user_id=:user_id "
                          "AND fixed_commitment_id=:id AND status!='done'",
                          {"user_id": user_id, "id": commitment_id})

    def update_committed_session(self, user_id: int, session_id: int, day: date, sport: str,
                                 intent: str, duration_min: int, status: str, updated_at: str) -> None:
        self._session.execute(
            text("UPDATE plan_sessions SET date=:date,sport=:sport,intent=:intent,duration_min=:duration,"
                 "status=:status,updated_at=:updated WHERE id=:id AND user_id=:user_id"),
            {"date": day.isoformat(), "sport": sport, "intent": intent, "duration": duration_min,
             "status": status, "updated": updated_at, "id": session_id, "user_id": user_id},
        )

    def insert_session(self, item: dict[str, Any], stamp: str) -> int:
        if item["sport"] == "mobility":
            result = self._session.execute(
                text("INSERT INTO plan_mobility_sessions(user_id,date,sport,intent,duration_min,hr_cap_bpm,"
                     "notes,origin,status,created_at,updated_at) "
                     "VALUES(:user_id,:date,'mobility','recovery',:duration,NULL,:notes,:origin,:status,:created,:updated)"),
                {"user_id": item["user_id"], "date": item["date"], "duration": item["duration_min"],
                 "notes": item.get("notes"), "origin": item["origin"],
                 "status": item.get("status", "planned"), "created": stamp, "updated": stamp},
            )
            return -int(result.lastrowid or 0)
        result = self._session.execute(
            text("INSERT INTO plan_sessions(user_id,date,sport,intent,duration_min,hr_cap_bpm,notes,origin,status,"
                 "linked_activity_id,fixed_commitment_id,workout_type,workout_json,created_at,updated_at) "
                 "VALUES(:user_id,:date,:sport,:intent,:duration,:hr_cap,:notes,:origin,:status,:linked,:fixed,"
                 ":workout_type,:workout_json,:created,:updated)"),
            {"user_id": item["user_id"], "date": item["date"], "sport": item["sport"],
             "intent": item["intent"], "duration": item["duration_min"], "hr_cap": item.get("hr_cap_bpm"),
             "notes": item.get("notes"), "origin": item["origin"], "status": item.get("status", "planned"),
             "linked": item.get("linked_activity_id"), "fixed": item.get("fixed_commitment_id"),
             "workout_type": item.get("workout_type"),
             "workout_json": json.dumps(item["workout"]) if item.get("workout") is not None
             else item.get("workout_json"), "created": stamp, "updated": stamp},
        )
        return int(result.lastrowid or 0)

    def update_plan_session(self, user_id: int, session_id: int, values: dict[str, Any],
                            updated_at: str, *, include_workout: bool = True) -> None:
        workout_fields = ",workout_type=:workout_type,workout_json=:workout_json" if include_workout else ""
        params = {"id": session_id, "user_id": user_id, "date": values["date"],
                  "sport": values["sport"], "intent": values["intent"],
                  "duration": values["duration_min"], "hr_cap": values.get("hr_cap_bpm"),
                  "notes": values.get("notes"), "status": values.get("status", "planned"),
                  "updated": updated_at}
        if include_workout:
            params.update(workout_type=values.get("workout_type"),
                          workout_json=json.dumps(values["workout"]) if values.get("workout") is not None
                          else values.get("workout_json"))
        self._session.execute(
            text("UPDATE plan_sessions SET date=:date,sport=:sport,intent=:intent,duration_min=:duration,"
                 "hr_cap_bpm=:hr_cap,notes=:notes,status=:status" + workout_fields +
                 ",updated_at=:updated WHERE id=:id AND user_id=:user_id"), params,
        )

    def update_mobility_session(self, user_id: int, session_id: int, values: dict[str, Any],
                                updated_at: str) -> None:
        self._session.execute(
            text("UPDATE plan_mobility_sessions SET duration_min=:duration,notes=:notes,status=:status,"
                 "updated_at=:updated WHERE id=:id AND user_id=:user_id"),
            {"duration": values["duration_min"], "notes": values.get("notes"),
             "status": values.get("status", "planned"), "updated": updated_at,
             "id": session_id, "user_id": user_id},
        )

    def any_session(self, user_id: int, session_id: int) -> dict[str, Any] | None:
        if session_id < 0:
            row = self._one("SELECT * FROM plan_mobility_sessions WHERE id=:id AND user_id=:user_id",
                            {"id": -session_id, "user_id": user_id})
            if row is not None:
                row["id"] = session_id
                row["linked_activity_id"] = None
                row["fixed_commitment_id"] = None
            return row
        return self.planned_session(user_id, session_id)

    def delete_session(self, user_id: int, session_id: int) -> None:
        table, identifier = (("plan_mobility_sessions", -session_id) if session_id < 0
                             else ("plan_sessions", session_id))
        self._session.execute(text(f"DELETE FROM {table} WHERE id=:id AND user_id=:user_id"),
                              {"id": identifier, "user_id": user_id})

    def restore_session(self, user_id: int, item: dict[str, Any], stamp: str) -> None:
        if item.get("id", 0) < 0:
            identifier = -item["id"]
            self._session.execute(
                text("INSERT INTO plan_mobility_sessions(id,user_id,date,sport,intent,duration_min,hr_cap_bpm,"
                     "notes,origin,status,created_at,updated_at) VALUES(:id,:user_id,:date,:sport,:intent,:duration,"
                     ":hr_cap,:notes,:origin,:status,:created,:updated)"),
                {"id": identifier, "user_id": user_id, "date": item["date"], "sport": item["sport"],
                 "intent": item["intent"], "duration": item["duration_min"], "hr_cap": item.get("hr_cap_bpm"),
                 "notes": item.get("notes"), "origin": item["origin"], "status": item["status"],
                 "created": stamp, "updated": stamp},
            )
            return
        self._session.execute(
            text("INSERT INTO plan_sessions(id,user_id,date,sport,intent,duration_min,hr_cap_bpm,notes,workout_type,"
                 "workout_json,origin,status,linked_activity_id,fixed_commitment_id,created_at,updated_at) "
                 "VALUES(:id,:user_id,:date,:sport,:intent,:duration,:hr_cap,:notes,:workout_type,:workout_json,"
                 ":origin,:status,:linked,:fixed,:created,:updated)"),
            {"id": item["id"], "user_id": user_id, "date": item["date"], "sport": item["sport"],
             "intent": item["intent"], "duration": item["duration_min"], "hr_cap": item.get("hr_cap_bpm"),
             "notes": item.get("notes"), "workout_type": item.get("workout_type"),
             "workout_json": item.get("workout_json"), "origin": item["origin"],
             "status": item["status"], "linked": item.get("linked_activity_id"),
             "fixed": item.get("fixed_commitment_id"), "created": stamp, "updated": stamp},
        )

    def restore_existing_session(self, user_id: int, session_id: int, item: dict[str, Any], stamp: str) -> None:
        if session_id < 0:
            self.update_mobility_session(user_id, -session_id, item, stamp)
            return
        self.update_plan_session(user_id, session_id, item, stamp, include_workout=True)

    def proposal_changes_decisions(self, proposal_id: int, changes: list[dict[str, Any]],
                                  accepted_ids: set[int]) -> None:
        for change in changes:
            self._session.execute(
                text("UPDATE proposal_changes SET decision=:decision WHERE id=:id"),
                {"decision": "accepted" if change["id"] in accepted_ids else "rejected",
                 "id": change["id"]},
            )

    def mark_stale(self, proposal_id: int) -> None:
        self.update_proposal_status(proposal_id, "stale")

    def mark_dismissed(self, user_id: int, proposal_id: int) -> bool:
        result = self._session.execute(
            text("UPDATE coach_proposals SET status='dismissed' WHERE id=:id AND user_id=:user_id "
                 "AND status='pending'"), {"id": proposal_id, "user_id": user_id},
        )
        if result.rowcount == 1:
            self._session.execute(text("UPDATE proposal_changes SET decision='rejected' WHERE proposal_id=:id"),
                                  {"id": proposal_id})
        return result.rowcount == 1

    def mark_superseded(self, proposal_id: int) -> None:
        self.update_proposal_status(proposal_id, "superseded")

    def link_activity(self, user_id: int, activity_id: int, day: date, sport: str,
                      updated_at: str) -> bool:
        row = self._one(
            "SELECT id FROM plan_sessions WHERE user_id=:user_id AND date=:date AND sport=:sport "
            "AND status='planned' AND linked_activity_id IS NULL "
            "ORDER BY CASE origin WHEN 'fixed' THEN 0 ELSE 1 END,id LIMIT 1",
            {"user_id": user_id, "date": day.isoformat(), "sport": sport},
        )
        if row is None:
            return False
        self._session.execute(
            text("UPDATE plan_sessions SET status='done',linked_activity_id=:activity_id,updated_at=:updated "
                 "WHERE id=:id AND user_id=:user_id"),
            {"activity_id": activity_id, "updated": updated_at, "id": row["id"], "user_id": user_id},
        )
        return True

    def skip_plan_session(self, user_id: int, session_id: int, updated_at: str) -> bool:
        result = self._session.execute(
            text("UPDATE plan_sessions SET status='skipped',updated_at=:updated WHERE id=:id "
                 "AND user_id=:user_id AND origin!='fixed' AND status='planned'"),
            {"updated": updated_at, "id": session_id, "user_id": user_id},
        )
        return result.rowcount == 1

    def proposal(self, user_id: int, proposal_id: int) -> dict[str, Any] | None:
        return self._one("SELECT * FROM coach_proposals WHERE id=:id AND user_id=:user_id",
                         {"id": proposal_id, "user_id": user_id})

    def proposal_changes(self, proposal_id: int) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM proposal_changes WHERE proposal_id=:id ORDER BY id", {"id": proposal_id})

    def proposals_for_week(self, user_id: int, start: date) -> list[dict[str, Any]]:
        end = start + timedelta(days=7)
        return self._rows("SELECT DISTINCT p.* FROM coach_proposals p JOIN proposal_changes c "
                          "ON c.proposal_id=p.id WHERE p.user_id=:user_id AND "
                          "json_extract(c.session_json,'$.date')>=:start AND "
                          "json_extract(c.session_json,'$.date')<:end ORDER BY p.id DESC LIMIT 20",
                          {"user_id": user_id, "start": start.isoformat(), "end": end.isoformat()})

    def insert_proposal(self, user_id: int, kind: str, summary: str, facts: list[dict[str, str]],
                        changes: list[dict[str, Any]], version: int, created_at: str) -> int:
        result = self._session.execute(
            text("INSERT INTO coach_proposals(user_id,kind,base_version,status,summary,facts_json,created_at) "
                 "VALUES(:user_id,:kind,:version,'pending',:summary,:facts,:created)"),
            {"user_id": user_id, "kind": kind, "version": version, "summary": summary,
             "facts": json.dumps(facts), "created": created_at},
        )
        proposal_id = int(result.lastrowid or 0)
        for index, change in enumerate(changes, start=1):
            self._session.execute(
                text("INSERT INTO proposal_changes(proposal_id,change_type,session_json,reason,fact_ids_json,"
                     "decision,group_id,workout_type,workout_json) "
                     "VALUES(:proposal_id,:change_type,:session,:reason,:fact_ids,'pending',:group_id,"
                     ":workout_type,:workout_json)"),
                {"proposal_id": proposal_id, "change_type": change["change_type"],
                 "session": json.dumps(change["session"]), "reason": change["reason"],
                 "fact_ids": json.dumps(change["fact_ids"]),
                 "group_id": change.get("group_id") or f"change-{index}",
                 "workout_type": change["session"].get("workout_type"),
                 "workout_json": json.dumps(change["session"]["workout"])
                 if change["session"].get("workout") is not None else None},
            )
        return proposal_id

    def update_proposal_status(self, proposal_id: int, status: str) -> None:
        self._session.execute(text("UPDATE coach_proposals SET status=:status WHERE id=:id"),
                              {"status": status, "id": proposal_id})

    def mark_proposal_changes(self, proposal_id: int, accepted_ids: set[int]) -> None:
        for change in self.proposal_changes(proposal_id):
            self._session.execute(
                text("UPDATE proposal_changes SET decision=:decision WHERE id=:id"),
                {"decision": "accepted" if change["id"] in accepted_ids else "rejected",
                 "id": change["id"]},
            )

    def save_snapshot(self, user_id: int, before_version: int, after_version: int,
                      snapshot: str, reason: str, created_at: str) -> int:
        result = self._session.execute(
            text("INSERT INTO plan_snapshots(user_id,version_before,version_after,snapshot_json,reason,created_at) "
                 "VALUES(:user_id,:before,:after,:snapshot,:reason,:created)"),
            {"user_id": user_id, "before": before_version, "after": after_version,
             "snapshot": snapshot, "reason": reason, "created": created_at},
        )
        return int(result.lastrowid or 0)

    def latest_snapshot(self, user_id: int) -> dict[str, Any] | None:
        return self._one("SELECT * FROM plan_snapshots WHERE user_id=:user_id AND undone_at IS NULL "
                         "ORDER BY id DESC LIMIT 1", {"user_id": user_id})

    def mark_snapshot_undone(self, snapshot_id: int, undone_at: str) -> None:
        self._session.execute(text("UPDATE plan_snapshots SET undone_at=:undone WHERE id=:id"),
                              {"undone": undone_at, "id": snapshot_id})

    def change_plan_session_status(self, user_id: int, session_id: int, status: str,
                                   updated_at: str) -> bool:
        if session_id < 0:
            result = self._session.execute(
                text("UPDATE plan_mobility_sessions SET status=:status,updated_at=:updated "
                     "WHERE id=:id AND user_id=:user_id"),
                {"status": status, "updated": updated_at, "id": -session_id, "user_id": user_id},
            )
            return result.rowcount == 1
        result = self._session.execute(
            text("UPDATE plan_sessions SET status=:status,updated_at=:updated "
                 "WHERE id=:id AND user_id=:user_id"),
            {"status": status, "updated": updated_at, "id": session_id, "user_id": user_id},
        )
        return result.rowcount == 1

    def commit(self) -> None:
        self._session.commit()

    def _one(self, query: str, params: dict[str, Any]) -> dict[str, Any] | None:
        row = self._session.execute(text(query), params).mappings().first()
        return dict(row) if row else None

    def _rows(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        return [dict(row) for row in self._session.execute(text(query), params).mappings()]

    def planned_session(self, user_id: int, session_id: int) -> dict[str, Any] | None:
        row = self._session.execute(
            text("SELECT * FROM plan_sessions WHERE id=:session_id AND user_id=:user_id"),
            {"session_id": session_id, "user_id": user_id},
        ).mappings().first()
        return dict(row) if row else None

    def update_workout_variant(self, user_id: int, session_id: int, duration_min: int,
                               workout: dict[str, Any]) -> dict[str, Any]:
        self._session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        result = self._session.execute(
            text("UPDATE plan_sessions SET duration_min=:duration_min,workout_json=:workout_json,"
                 "updated_at=CURRENT_TIMESTAMP WHERE id=:session_id AND user_id=:user_id AND status='planned'"),
            {"duration_min": duration_min, "workout_json": json.dumps(workout),
             "session_id": session_id, "user_id": user_id},
        )
        if result.rowcount != 1:
            raise ValueError("Only a planned session can switch to its shorter version")
        self._session.execute(
            text("INSERT INTO plan_versions(user_id,version) VALUES(:user_id,1) "
                 "ON CONFLICT(user_id) DO UPDATE SET version=version+1"),
            {"user_id": user_id},
        )
        updated = self.planned_session(user_id, session_id)
        if updated is None:
            raise ValueError("Planned session not found")
        return updated
