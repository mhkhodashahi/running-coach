"""Daily decision orchestration; rules decide, the model may only explain."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from coach.agent import CoachAgent, _read_version, _user_lock
from coach.decision import (
    RECENT_RECOVERY_WINDOW,
    SPORT_WINDOW,
    TEAM_SPORTS,
    PriorSession,
    decide_intensity,
    is_hard_session,
    provisional_day,
    rank_sports,
    session_cause,
    team_options,
)
from coach.guardrails import GuardrailContext, guardrail_errors
from config import Settings, get_settings
from llm.base import NullLLMClient
from llm.factory import get_llm_client
from metrics import get_daily_snapshot
from metrics.sports import RECOMMENDABLE_SPORTS, sport_category
from services.coach_facts import unsupported_text_numbers
from services.fact_display import ratio as format_ratio
from services.fact_display import score as format_score
from services.hr_zones import heart_rate_zone_bounds

PROMPT_VERSION = "daily-v2.3"
SYSTEM_PROMPT = (
    "You are Pulse Coach. Explain the code's daily decision; never change its intensity or ranked sports. "
    "Speak as I to you. No diagnosis. Return exactly the JSON schema fields. "
    "Use only supplied fact display strings for numerical claims. Cite at least two facts: put their IDs in "
    "evidence_ids, and copy their display values exactly into the explanation. Never put IDs in prose. "
    "The explanation and headline are statements, never questions. Put questions only in follow_ups. "
    "The explanation must be 2 or 3 short sentences. Give 2 or 3 short, answerable follow-up questions. "
    "Do not mention internal rules, scores, thresholds, dates or durations unless their exact display appears in facts. "
    "Never mention sync time, provisional status or the health day used; the UI displays those separately."
)


class DecisionExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    headline: str = Field(min_length=1, max_length=120)
    explanation: str = Field(min_length=1, max_length=700)
    evidence_ids: list[str] = Field(default_factory=list)
    follow_ups: list[str] = Field(default_factory=list, max_length=3)


@dataclass(frozen=True)
class DailyDecision:
    date: str
    based_on: str
    provisional: bool
    last_sync_time: str
    readiness: float | None
    hrv_component: float | None
    intensity: str
    rule: str
    rule_fact_ids: tuple[str, ...]
    sports: tuple[dict[str, Any], ...]
    optional: str | None
    facts: tuple[dict[str, str], ...]
    headline: str
    explanation: str
    evidence_ids: tuple[str, ...]
    follow_ups: tuple[str, ...]
    athlete_choice: str | None = None
    team_options: tuple[dict[str, str], ...] = ()
    explanation_source: str = "unknown"


def _read_only(database: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _fact(fact_id: str, metric: str, display: str, source: str) -> dict[str, str]:
    return {"id": fact_id, "metric": metric, "display": display, "source": source}


def _session_time(connection: sqlite3.Connection, activity_id: int, day: date, timezone: str) -> datetime:
    row = connection.execute("SELECT MIN(timestamp) FROM activity_track_points WHERE activity_id=?", (activity_id,)).fetchone()
    if row and row[0]:
        stamp = datetime.fromisoformat(row[0])
        return stamp.replace(tzinfo=ZoneInfo(timezone)) if stamp.tzinfo is None else stamp.astimezone(ZoneInfo(timezone))
    return datetime.combine(day, time.min, ZoneInfo(timezone))


def _recent_sessions(connection: sqlite3.Connection, user_id: int, requested: date, timezone: str,
                     snapshot: Any) -> tuple[PriorSession, ...]:
    rows = connection.execute(
        "SELECT a.id,a.date,a.type,a.planned_intent,i.payload_json,e.rpe FROM activities a "
        "LEFT JOIN activity_coaching_insights i ON i.activity_id=a.id "
        "LEFT JOIN activity_efforts e ON e.activity_id=a.id "
        "WHERE a.user_id=? AND a.date>=? AND a.date<=? ORDER BY a.date,a.id",
        (user_id, (requested - timedelta(days=7)).isoformat(), requested.isoformat()),
    ).fetchall()
    by_id = {item.activity_id: item for item in snapshot.sessions}
    sessions = []
    for row in rows:
        sport = sport_category(row["type"], requested)
        if sport not in RECOMMENDABLE_SPORTS:
            continue
        detail = by_id.get(row["id"])
        z4_share = (sum(zone.percent.value or 0 for zone in detail.zones if zone.name.startswith(("Z4", "Z5")))
                    if detail else None)
        detected = None
        if row["payload_json"]:
            try:
                detected = json.loads(row["payload_json"]).get("intent", {}).get("detected")
            except (ValueError, AttributeError):
                pass
        if detected is None and detail:
            z34 = sum(zone.percent.value or 0 for zone in detail.zones if zone.name.startswith(("Z3", "Z4")))
            if z4_share is not None and z4_share >= 50:
                detected = "race"
            elif z34 >= 60:
                detected = "tempo"
        sessions.append(PriorSession(_session_time(connection, row["id"], date.fromisoformat(row["date"]), timezone),
                                     sport, detected, z4_share, row["rpe"]))
    return tuple(sessions)


def build_daily_decision(requested: date, database: Path, user_id: int, timezone: str,
                         sleep_goal_hours: float, hr_zones: tuple[tuple[str, int, int | None], ...] = ()) -> DailyDecision:
    """Read the DB but never write it; all rankings and intensity come from code."""
    with _read_only(database) as connection:
        rows = connection.execute("SELECT date,sleep_duration,hrv FROM health_metrics "
                                  "WHERE user_id=? AND date<=? ORDER BY date DESC", (user_id, requested.isoformat()))
        health = tuple((date.fromisoformat(row[0]), row[1], row[2]) for row in rows)
        based_on, provisional = provisional_day(requested, health)
        sync = connection.execute("SELECT last_synced_at FROM garmin_sync_status WHERE user_id=?", (user_id,)).fetchone()
        sync_display = "never synced"
        if sync and sync[0]:
            stamp = datetime.fromisoformat(sync[0])
            sync_display = (stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp).astimezone(
                ZoneInfo(timezone)).strftime("%Y-%m-%d %H:%M %Z")
        snapshot = get_daily_snapshot(based_on, database=database, user_id=user_id,
                                      timezone=timezone, sleep_goal_hours=sleep_goal_hours, hr_zones=hr_zones)
        # The date-only activity fallback is midnight; no later activity can influence an earlier decision.
        session_snapshot = (snapshot if based_on == requested else
                            get_daily_snapshot(requested, database=database, user_id=user_id,
                                               timezone=timezone, sleep_goal_hours=sleep_goal_hours,
                                               hr_zones=hr_zones))
        sessions = _recent_sessions(connection, user_id, requested, timezone, session_snapshot)
        user = connection.execute("SELECT max_hr,age FROM users WHERE id=?", (user_id,)).fetchone()
        fixed_teams = connection.execute(
            "SELECT f.sport FROM fixed_commitments f WHERE f.user_id=? AND f.weekday=? AND f.active=1 "
            "AND NOT EXISTS (SELECT 1 FROM plan_sessions p WHERE p.user_id=f.user_id "
            "AND p.fixed_commitment_id=f.id AND p.date=? AND p.status='skipped')",
            (user_id, requested.weekday(), requested.isoformat())).fetchall()
        planned_teams = connection.execute("SELECT sport FROM plan_sessions WHERE user_id=? AND date=? "
                                           "AND sport IN ('football','volleyball') AND status='planned'",
                                           (user_id, requested.isoformat())).fetchall()
        active_goal = connection.execute(
            "SELECT goal_type,target_distance_km FROM goals WHERE user_id=? AND is_active=1 LIMIT 1",
            (user_id,)).fetchone()
        running_goal = bool(active_goal and active_goal[0] in
                            ('running_pb', 'marathon_pb', '5k_pb', '10k_pb', 'half_marathon_pb'))
    now = datetime.combine(requested + timedelta(days=1), time.min, ZoneInfo(timezone))
    scheduled_teams = tuple(dict.fromkeys(row[0] for row in (*fixed_teams, *planned_teams)))
    recent = tuple(item for item in sessions if item.when < now)
    readiness = snapshot.readiness.score.value
    load_ratio = snapshot.load.ratio.value
    illness = snapshot.readiness.illness_flag.value
    intensity = decide_intensity(illness, readiness, load_ratio, recent, now)
    max_hr = user[0] or (220 - user[1] if user and user[1] else None) if user else None
    z2_cap = None
    if hr_zones:
        z2_cap = hr_zones[1][2] if len(hr_zones) >= 2 else None
        z4 = (hr_zones[3][1], hr_zones[3][2]) if len(hr_zones) >= 4 and hr_zones[3][2] is not None else None
    elif max_hr:
        bounds = heart_rate_zone_bounds(int(max_hr))
        z2_cap = int(bounds[1][2] - 1e-9)
        z4 = (math.ceil(bounds[3][1]), int(bounds[3][2] - 1e-9))
    else:
        z4 = None
    ranking = rank_sports(intensity.intensity, recent, now, z2_cap, readiness=readiness,
                          team_commitments=scheduled_teams, z4_bounds_bpm=z4,
                          running_goal=running_goal)
    hard_recent = max((item for item in recent if now - timedelta(hours=48) <= item.when < now and
                       is_hard_session(item)), key=lambda item: item.when, default=None)
    facts = [
        _fact("READINESS", "Readiness", format_score(readiness) or "No data", "metrics_snapshot.readiness.score"),
        _fact("LOAD_RATIO", "Load ratio", format_ratio(load_ratio) or "No data", "metrics_snapshot.load.ratio"),
        _fact("ILLNESS_FLAG", "Illness signal", "resting HR and HRV signal strain" if illness else
              "no combined illness signal" if illness is False else "No data",
              "metrics_snapshot.readiness.illness_flag"),
        _fact("HARD_LAST_48H", "Hard session in last 48h",
              session_cause(hard_recent) if hard_recent else "no hard session in last 48 hours",
              "activities + HR zones"),
        _fact("BASED_ON_DATE", "Health day used", based_on.isoformat(), "health_metrics.date"),
        _fact("LAST_SYNC_TIME", "Last Garmin sync", sync_display, "garmin_sync_status.last_synced_at"),
    ]
    if active_goal:
        facts.append(_fact("ACTIVE_GOAL", "Active goal",
                           f"{active_goal[1]:g} km {active_goal[0].replace('_', ' ')}",
                           "goals.goal_type,target_distance_km"))
    for sport in RECOMMENDABLE_SPORTS:
        count = sum(now - SPORT_WINDOW <= item.when < now and item.sport == sport for item in recent)
        last_sport = max((item for item in recent if now - timedelta(hours=24) <= item.when < now and
                          item.sport == sport), key=lambda item: item.when, default=None)
        facts.append(_fact(f"SPORT_{sport.upper()}_7D", f"{sport} last 7 days", str(count), "activities.date,type"))
        facts.append(_fact(f"SPORT_{sport.upper()}_LAST_24H", f"{sport} last 24h",
                           session_cause(last_sport) if last_sport else f"no {sport} session in last 24 hours",
                           "activities.date,type"))
        if sport in ("running", "gym"):
            count_3d = sum(now - RECENT_RECOVERY_WINDOW <= item.when < now and item.sport == sport for item in recent)
            facts.append(_fact(f"SPORT_{sport.upper()}_3D", f"{sport} last 3 days", str(count_3d),
                               "activities.date,type"))
    for sport in TEAM_SPORTS:
        facts.append(_fact(f"TEAM_{sport.upper()}_TODAY", f"{sport} team training today",
                           f"{sport} training planned today" if sport in scheduled_teams else
                           f"no {sport} training planned today", "explicit_team_schedule"))
    last_team = max((item for item in recent if now - timedelta(hours=48) <= item.when < now and
                     item.sport in TEAM_SPORTS), key=lambda item: item.when, default=None)
    facts.append(_fact("TEAM_LAST_48H", "Team session last 48h",
                       session_cause(last_team) if last_team else "no team session in last 48 hours",
                       "activities.date,type"))
    facts.extend((_fact("HARD_LOOKBACK", "Hard-session lookback", "48 hours", "coach.decision.HARD_LOOKBACK"),
                  _fact("RECENT_SPORT_WINDOW", "Recent sport window", "24 hours", "coach.decision.RECENT_SPORT"),
                  _fact("SPORT_RECOVERY_WINDOW", "Sport recovery window", "3 days",
                        "coach.decision.RECENT_RECOVERY_WINDOW"),
                  _fact("SPORT_WINDOW", "Sport ranking window", "7 days", "coach.decision.SPORT_WINDOW")))
    for item in ranking:
        sport = item.sport.upper()
        if item.sport not in TEAM_SPORTS:
            facts.append(_fact(f"SPORT_{sport}_REASON", f"{item.sport} recommendation reason",
                               item.reason, "activities.date,type + detected_intent"))
        facts.append(_fact(f"SPORT_{sport}_DURATION", f"{item.sport} suggested duration",
                           f"{item.session['duration_min']} min", "coach.decision.session.duration_min"))
        cap = item.session["hr_cap_bpm"]
        if isinstance(cap, int):
            facts.append(_fact(f"SPORT_{sport}_HR_CAP", f"{item.sport} suggested HR cap",
                               f"{cap} bpm", "coach.decision.session.hr_cap_bpm"))
    decision = DailyDecision(requested.isoformat(), based_on.isoformat(), provisional, sync_display,
                             readiness, next((item.score.value for item in snapshot.readiness.components
                                              if item.name == "hrv"), None), intensity.intensity, intensity.rule,
                             intensity.fact_ids, tuple(asdict(item) for item in ranking),
                             ("Skip planned team training or attend skills only. Optional mobility or a walk; not training."
                              if intensity.intensity == "rest" and scheduled_teams else
                              "Optional mobility or a walk; not training" if intensity.intensity == "rest" else None),
                             tuple(facts), "", "", (), (), team_options=team_options(intensity.intensity, scheduled_teams))
    return with_fallback(decision)


def fallback_explanation(decision: DailyDecision) -> str:
    """Plain, rule-specific explanation without internal IDs or thresholds."""
    readiness = format_score(decision.readiness) or "No data"
    load_ratio = next((fact["display"] for fact in decision.facts if fact["id"] == "LOAD_RATIO"), "No data")
    sentences = {
        "illness_signal": "Rest today. Your resting HR and HRV both point to strain. If this persists, see a doctor.",
        "readiness_below_30": f"Rest today. Readiness is {readiness}, so recovery takes priority.",
        "not_enough_data": "Keep today easy. There is not enough recovery data to support a hard session.",
        "readiness_below_50": f"Keep today easy. Readiness is {readiness}, so protect recovery.",
        "load_ratio_above_1_5": ("Keep today easy. Your training load is well above your usual level "
                                   f"(load ratio {load_ratio})."),
        "load_ratio_above_1_3": (f"Keep today easy. Your load ratio is {load_ratio}, above the range "
                                   "for a hard session."),
        "hard_allowed": (f"A hard session is available today. Readiness is {readiness}, and recent load "
                         f"is within range (ratio {load_ratio})."),
        "hard_in_last_48h": "Keep today easy. You had a hard session in the last 48 hours.",
        "otherwise_easy": (f"Keep today easy. Readiness is {readiness}; the conditions for a hard session "
                           "are not all met."),
    }
    result = sentences[decision.rule]
    return result


def with_fallback(decision: DailyDecision) -> DailyDecision:
    """Do not expose an unadorned code decision with empty copy."""
    if decision.headline.strip() and decision.explanation.strip():
        return decision
    return replace(decision, headline=f"{decision.intensity.title()} today.",
                   explanation=fallback_explanation(decision),
                   evidence_ids=decision.rule_fact_ids,
                   explanation_source="fallback")


def _validate_explanation(payload: Any, decision: DailyDecision) -> DecisionExplanation:
    result = DecisionExplanation.model_validate(payload)
    if not result.headline.strip() or not result.explanation.strip():
        raise ValueError("Headline and explanation cannot be blank")
    facts = {item["id"]: item for item in decision.facts}
    if len(result.evidence_ids) < 2 or set(result.evidence_ids) - facts.keys():
        raise ValueError("Two known evidence IDs are required")
    text = f"{result.headline} {result.explanation}"
    if "?" in text or re.search(r"(?:^|[.!]\s+)(?:what|why|how|should|would|could|do|did|is|are|can|when|where)\b",
                               text, flags=re.IGNORECASE):
        raise ValueError("Headline and explanation must be statements; put questions in follow_ups")
    if any(re.search(rf"(?<![A-Za-z0-9_]){re.escape(fact_id)}(?![A-Za-z0-9_])", text) for fact_id in facts):
        raise ValueError("Fact ID in prose")
    if re.search(r"\b(?:provisional|last sync|synced)\b", text, re.IGNORECASE) or decision.based_on in text:
        raise ValueError("Sync and provisional details belong in the UI, not the explanation")
    unsupported = unsupported_text_numbers(text, list(facts.values()))
    if unsupported:
        raise ValueError("Unsupported numbers: " + ", ".join(unsupported))
    missing = [facts[item]["display"] for item in result.evidence_ids[:2]
               if facts[item]["display"].casefold() not in text.casefold()]
    if missing:
        raise ValueError("Cited values missing from explanation: " + ", ".join(missing))
    sentences = [part for part in re.split(r"(?<=[.!?])\s+", result.explanation.strip()) if part]
    if not 2 <= len(sentences) <= 3:
        raise ValueError("Explanation must be 2 or 3 sentences")
    errors = guardrail_errors(text, GuardrailContext(decision.rule == "illness_signal", None, False))
    if errors:
        raise ValueError("; ".join(errors))
    if not 2 <= len(result.follow_ups) <= 3:
        raise ValueError("Need 2 or 3 follow-up questions")
    return result


def explain_decision(decision: DailyDecision, llm: Any | None = None,
                     count_request: Any | None = None,
                     on_error: Callable[[int, str], None] | None = None) -> DailyDecision:
    """The model receives no mutable choice fields; bad output cannot change the decision."""
    fallback = fallback_explanation(decision)
    defaults = ("How has my recovery changed?", "Which sessions affected today's load?")
    if llm is None:
        return replace(decision, headline=f"{decision.intensity.title()} today.", explanation=fallback,
                       evidence_ids=decision.rule_fact_ids, follow_ups=defaults, explanation_source="fallback")
    explanation_fact_ids = {"READINESS", "LOAD_RATIO", "ILLNESS_FLAG", "HARD_LAST_48H", "HARD_LOOKBACK"}
    context = {"intensity": decision.intensity,
               "top_sport": decision.sports[0]["sport"] if decision.sports else None,
               "facts": [fact for fact in decision.facts if fact["id"] in explanation_fact_ids and
                         (fact["id"] != "ILLNESS_FLAG" or decision.rule == "illness_signal")],
               "decision_basis": fallback_explanation(decision)}
    prompt = (json.dumps(context) + "\nWrite 2-3 sentences. Cite two facts whose display values are "
              "copied verbatim into the explanation. Do not add fields outside the response schema.")
    for attempt in range(2):
        try:
            if count_request is not None:
                count_request()
            response = llm.generate_json(SYSTEM_PROMPT, prompt, response_schema=DecisionExplanation)
            result = _validate_explanation(response, decision)
            return replace(decision, headline=result.headline, explanation=result.explanation,
                           evidence_ids=tuple(result.evidence_ids), follow_ups=tuple(result.follow_ups),
                           explanation_source="llm")
        except Exception as exc:
            if on_error is not None:
                on_error(attempt + 1, f"{type(exc).__name__}: {exc}")
            prompt += (f"\nValidation error: {exc}. Correct the JSON without changing the code decision. "
                       "For unsupported numbers, copy the exact fact display or remove the claim. "
                       "Do not introduce another number.")
    return replace(decision, headline=f"{decision.intensity.title()} today.", explanation=fallback,
                   evidence_ids=decision.rule_fact_ids, follow_ups=defaults, explanation_source="fallback")


def get_or_create_daily_decision(day: date, *, settings: Settings | None = None,
                                 user_id: int | None = None, llm: Any | None = None,
                                 on_explanation_error: Callable[[int, str], None] | None = None) -> DailyDecision:
    """Recompute on changed inputs; store immutable coach choice and separate athlete override."""
    settings = settings or get_settings()
    _read_version(settings.db_path)
    user_id = user_id or settings.default_user_id
    with _user_lock(settings.db_path, user_id):
        candidate = build_daily_decision(day, settings.db_path, user_id, settings.local_timezone,
                                         settings.sleep_goal_hours, settings.hr_zones)
        fingerprint = hashlib.sha256(json.dumps({"candidate": asdict(candidate),
                                                 "prompt_version": PROMPT_VERSION}, sort_keys=True).encode()).hexdigest()
        with sqlite3.connect(settings.db_path) as connection:
            old = connection.execute("SELECT payload_json FROM coaching_decisions WHERE user_id=? AND "
                                     "decision_type='daily_v2' AND decision_date=? ORDER BY id DESC LIMIT 1",
                                     (user_id, day.isoformat())).fetchone()
        previous = json.loads(old[0]) if old else {}
        if previous.get("input_hash") == fingerprint:
            cached = with_fallback(DailyDecision(**previous["decision"]))
            from coach.planning import propose_daily_conflict

            propose_daily_conflict(day, cached.intensity, list(cached.facts), settings=settings, user_id=user_id)
            return cached
        client = llm or get_llm_client(settings.llm_provider, settings.openai_api_key, settings.openai_model,
                                       settings.ollama_base_url, settings.ollama_model)
        if isinstance(client, NullLLMClient):
            client = None
        if settings.llm_provider in ("openai", "chatgpt") and not (
                settings.allow_remote_llm and settings.remote_athlete_data_approved):
            client = None
        agent = CoachAgent(settings, client, user_id) if client is not None else None
        decision = explain_decision(candidate, client, agent._count_request if agent else None,
                                    on_explanation_error)
        decision = replace(decision, athlete_choice=previous.get("athlete_choice"))
        payload = {"decision": asdict(decision), "athlete_choice": decision.athlete_choice,
                   "input_hash": fingerprint, "prompt_version": PROMPT_VERSION}
        with sqlite3.connect(settings.db_path) as connection:
            connection.execute("INSERT INTO coaching_decisions "
                               "(user_id,goal_id,decision_type,decision_date,summary,risk_level,payload_json,created_at) "
                               "VALUES(?,NULL,'daily_v2',?,?,?,?,?)",
                               (user_id, day.isoformat(), decision.headline,
                                "high" if decision.intensity == "rest" else "moderate" if decision.intensity == "easy" else "low",
                                json.dumps(payload), datetime.now(UTC).replace(tzinfo=None).isoformat()))
        from coach.planning import propose_daily_conflict

        propose_daily_conflict(day, decision.intensity, list(decision.facts), settings=settings, user_id=user_id)
        return decision


def set_athlete_choice(day: date, choice: str | None, *, settings: Settings | None = None,
                       user_id: int | None = None) -> DailyDecision:
    if choice not in (None, "rest", "easy", "hard"):
        raise ValueError("Athlete choice must be rest, easy, hard or none")
    settings = settings or get_settings()
    user_id = user_id or settings.default_user_id
    with sqlite3.connect(settings.db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT id,payload_json FROM coaching_decisions WHERE user_id=? AND "
                                 "decision_type='daily_v2' AND decision_date=? ORDER BY id DESC LIMIT 1",
                                 (user_id, day.isoformat())).fetchone()
        if row is None:
            raise ValueError("Daily decision has not been generated")
        payload = json.loads(row[1])
        payload["athlete_choice"] = choice
        payload["decision"]["athlete_choice"] = choice
        connection.execute("UPDATE coaching_decisions SET payload_json=? WHERE id=?",
                           (json.dumps(payload), row[0]))
    return DailyDecision(**payload["decision"])
