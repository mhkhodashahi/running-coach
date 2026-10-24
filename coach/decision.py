"""Pure, deterministic daily intensity and sport ranking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

from metrics.sports import RECOMMENDABLE_SPORTS

REST_READINESS = 30.0
EASY_READINESS = 50.0
HARD_READINESS = 70.0
HARD_LOAD_RATIO = 1.3
EASY_LOAD_RATIO = 1.5
HARD_Z4_SHARE = 15.0
HARD_LOOKBACK = timedelta(hours=48)
RECENT_SPORT = timedelta(hours=24)
RECENT_TEAM = timedelta(hours=48)
RECENT_RECOVERY_WINDOW = timedelta(days=3)
SPORT_WINDOW = timedelta(days=7)
EASY_DURATION_MIN = 30
EASY_LONG_DURATION_MIN = 45
TEMPO_WARMUP_MIN = 10
TEMPO_REPEATS = 3
TEMPO_WORK_MIN = 8
TEMPO_RECOVERY_MIN = 2
TEMPO_COOLDOWN_MIN = 10
HARD_DURATION_MIN = (TEMPO_WARMUP_MIN + TEMPO_REPEATS * TEMPO_WORK_MIN +
                     (TEMPO_REPEATS - 1) * TEMPO_RECOVERY_MIN + TEMPO_COOLDOWN_MIN)
HARD_GYM_DURATION_MIN = 45
SKILLS_DURATION_MIN = 30
SOLO_SPORTS = ("running", "gym")
TEAM_SPORTS = ("football", "volleyball")

Intensity = Literal["rest", "easy", "hard"]


@dataclass(frozen=True)
class PriorSession:
    when: datetime
    sport: str
    detected_intent: str | None = None
    z4_plus_percent: float | None = None
    rpe: int | None = None


@dataclass(frozen=True)
class IntensityDecision:
    intensity: Intensity
    rule: str
    fact_ids: tuple[str, ...]


@dataclass(frozen=True)
class RankedSport:
    rank: int
    sport: str
    session: dict[str, str | int | None]
    reason: str
    fact_ids: tuple[str, ...]


def is_hard_session(session: PriorSession) -> bool:
    return ((session.rpe is not None and session.rpe >= 7) or
            (session.rpe is None and session.sport in TEAM_SPORTS) or
            session.detected_intent in ("tempo", "race") or
            (session.z4_plus_percent is not None and session.z4_plus_percent >= HARD_Z4_SHARE))


def session_cause(session: PriorSession) -> str:
    """Describe a recorded session without guessing whether team play was a match."""
    if session.rpe is not None and session.rpe >= 7:
        label = f"{session.sport} effort rated {session.rpe}/10"
    elif session.sport in TEAM_SPORTS:
        label = f"{session.sport} session"
    elif session.detected_intent in ("tempo", "race"):
        label = f"{session.detected_intent} run"
    elif session.z4_plus_percent is not None and session.z4_plus_percent >= HARD_Z4_SHARE:
        label = "high-intensity run"
    else:
        label = f"{session.sport} session"
    return f"{label} on {session.when:%a} {session.when.day} {session.when:%b}"


def decide_intensity(illness: bool | None, readiness: float | None, load_ratio: float | None,
                     sessions: tuple[PriorSession, ...], now: datetime) -> IntensityDecision:
    if illness is True:
        return IntensityDecision("rest", "illness_signal", ("ILLNESS_FLAG",))
    if readiness is not None and readiness < REST_READINESS:
        return IntensityDecision("rest", "readiness_below_30", ("READINESS",))
    if readiness is None:
        return IntensityDecision("easy", "not_enough_data", ("READINESS",))
    if readiness < EASY_READINESS:
        return IntensityDecision("easy", "readiness_below_50", ("READINESS",))
    if load_ratio is not None and load_ratio > EASY_LOAD_RATIO:
        return IntensityDecision("easy", "load_ratio_above_1_5", ("LOAD_RATIO",))
    if load_ratio is not None and load_ratio > HARD_LOAD_RATIO:
        return IntensityDecision("easy", "load_ratio_above_1_3", ("LOAD_RATIO",))
    recent_hard = any(now - HARD_LOOKBACK <= item.when < now and is_hard_session(item) for item in sessions)
    if readiness >= HARD_READINESS and load_ratio is not None and load_ratio <= HARD_LOAD_RATIO and not recent_hard:
        return IntensityDecision("hard", "hard_allowed", ("READINESS", "LOAD_RATIO", "HARD_LAST_48H"))
    if recent_hard:
        return IntensityDecision("easy", "hard_in_last_48h", ("HARD_LAST_48H", "READINESS"))
    return IntensityDecision("easy", "otherwise_easy", ("READINESS", "LOAD_RATIO"))


def rank_sports(intensity: Intensity, sessions: tuple[PriorSession, ...], now: datetime,
                z2_cap_bpm: int | None, *, readiness: float | None = None,
                team_commitments: tuple[str, ...] = (),
                z4_bounds_bpm: tuple[int, int] | None = None) -> tuple[RankedSport, ...]:
    if intensity == "rest":
        return ()
    counts = {sport: sum(now - SPORT_WINDOW <= item.when < now and item.sport == sport
                         for item in sessions) for sport in RECOMMENDABLE_SPORTS}
    recent_counts = {sport: sum(now - RECENT_RECOVERY_WINDOW <= item.when < now and item.sport == sport
                                for item in sessions) for sport in SOLO_SPORTS}
    recent = {sport: any(now - RECENT_SPORT <= item.when < now and item.sport == sport
                         for item in sessions) for sport in RECOMMENDABLE_SPORTS}
    latest = {sport: max((item for item in sessions if now - SPORT_WINDOW <= item.when < now and
                          item.sport == sport), key=lambda item: item.when, default=None) for sport in SOLO_SPORTS}
    solo_order = sorted(SOLO_SPORTS,
                        key=lambda sport: (int(recent[sport]), recent_counts[sport], counts[sport],
                                           SOLO_SPORTS.index(sport)))
    committed = tuple(dict.fromkeys(sport for sport in team_commitments if sport in TEAM_SPORTS))
    order = (*committed, *solo_order)
    result = []
    for index, sport in enumerate(order, 1):
        if sport == "running":
            if intensity == "hard":
                target = (f"{z4_bounds_bpm[0]}–{z4_bounds_bpm[1]} bpm" if z4_bounds_bpm else "threshold effort")
                structure = (f"{TEMPO_WARMUP_MIN} min easy, {TEMPO_REPEATS} × {TEMPO_WORK_MIN} min at {target} "
                             f"with {TEMPO_RECOVERY_MIN} min easy, {TEMPO_COOLDOWN_MIN} min easy")
            else:
                structure = f"HR under {z2_cap_bpm} bpm" if z2_cap_bpm is not None else "Easy conversational effort"
            session = {"sport": sport, "intent": "tempo" if intensity == "hard" else "easy",
                       "duration_min": HARD_DURATION_MIN if intensity == "hard" else
                       EASY_LONG_DURATION_MIN if readiness is not None and readiness >= HARD_READINESS else EASY_DURATION_MIN,
                       "hr_cap_bpm": z2_cap_bpm if intensity == "easy" else None,
                       "structure": structure}
        elif sport == "gym":
            session = {"sport": sport, "intent": "strength" if intensity == "hard" else "light or upper body",
                       "duration_min": HARD_GYM_DURATION_MIN if intensity == "hard" else
                       EASY_LONG_DURATION_MIN if readiness is not None and readiness >= HARD_READINESS else EASY_DURATION_MIN,
                       "hr_cap_bpm": None,
                       "structure": f"strength, full body, {HARD_GYM_DURATION_MIN} min" if intensity == "hard" else
                       "Light or upper-body strength"}
        else:
            session = {"sport": sport, "intent": "team training" if intensity == "hard" else "skills only, no match play",
                       "duration_min": SKILLS_DURATION_MIN, "hr_cap_bpm": None,
                       "structure": "Team training" if intensity == "hard" else "Skills only, no match play"}
        if sport in TEAM_SPORTS:
            reason = "Team training is planned today."
            ids = (f"TEAM_{sport.upper()}_TODAY",)
        else:
            prior = latest[sport]
            if prior is None:
                reason = f"No {sport if sport == 'gym' else 'run'} this week."
            else:
                label = "run" if sport == "running" else "gym"
                intent = f", {prior.detected_intent}" if prior.detected_intent in ("recovery", "easy", "steady", "tempo", "race") else ""
                reason = f"Last {label} {prior.when:%a}{intent}."
                if recent[sport]:
                    reason += " Give it recovery time."
            ids = (f"SPORT_{sport.upper()}_REASON", f"SPORT_{sport.upper()}_LAST_24H",
                   f"SPORT_{sport.upper()}_3D", f"SPORT_{sport.upper()}_7D")
        result.append(RankedSport(index, sport, session, reason, ids))
    return tuple(result)


def team_options(intensity: Intensity, team_commitments: tuple[str, ...] = ()) -> tuple[dict[str, str], ...]:
    committed = set(team_commitments) & set(TEAM_SPORTS)
    result = []
    for sport in TEAM_SPORTS:
        if sport in committed and intensity != "rest":
            continue
        if sport in committed and intensity == "rest":
            label = "Skip team training or attend skills only"
        else:
            label = "Only with team training today"
        result.append({"sport": sport, "label": label})
    return tuple(result)


def provisional_day(requested: date, health: tuple[tuple[date, float | None, float | None], ...]) -> tuple[date, bool]:
    for day, sleep, hrv in sorted(health, key=lambda row: row[0], reverse=True):
        if day <= requested and sleep is not None and hrv is not None:
            return day, day != requested
    return requested, True
