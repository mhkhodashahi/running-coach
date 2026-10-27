"""Pure, bounded Telegram message formatting; no database or transport access."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from html import escape
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit


@dataclass(frozen=True)
class OutboundMessage:
    html: str
    plain: str
    keyboard: tuple[tuple[dict[str, str], ...], ...] = ()


def short_date(day: date) -> str:
    return f"{day:%a} {day.day} {day:%b}"


def public_link(base: str, path: str) -> str | None:
    """Only explicit, non-loopback HTTPS addresses may appear in Telegram."""
    parsed = urlsplit(base.strip())
    host = parsed.hostname or ""
    try:
        loopback = ip_address(host).is_loopback
    except ValueError:
        loopback = host.lower() in {"localhost", "localhost.localdomain"}
    if (parsed.scheme != "https" or not host or loopback or parsed.username or parsed.password or
            parsed.query or parsed.fragment):
        return None
    return base.rstrip("/") + path


def rating_keyboard(unrated: list[tuple[int, str]]) -> tuple[tuple[dict[str, str], ...], ...]:
    rows: list[tuple[dict[str, str], ...]] = []
    for activity_id, _ in unrated[:2]:
        for start, stop in ((0, 6), (6, 11)):
            rows.append(tuple({"text": str(value), "callback_data": f"rpe:{activity_id}:{value}"}
                              for value in range(start, stop)))
    return tuple(rows)


def _render(lines: list[str], keyboard: tuple[tuple[dict[str, str], ...], ...] = ()) -> OutboundMessage:
    return OutboundMessage("\n".join([f"<b>{escape(lines[0])}</b>", *(escape(line) for line in lines[1:])]),
                           "\n".join(lines), keyboard)


def _top_session(decision: Any) -> str | None:
    if not decision.sports:
        return None
    top = decision.sports[0]
    session = top["session"]
    sport = "Run" if top["sport"] == "running" else top["sport"].title()
    return f"{sport} {session['duration_min']} min: {session['structure']}"


def decision_reason(decision: Any) -> str:
    """Only display values from the decision's facts can justify a message."""
    facts = {item["id"]: item["display"] for item in decision.facts}
    rhr, hrv = facts.get("RHR_DELTA"), facts.get("HRV_DELTA")
    if decision.rule == "illness_signal" and rhr not in (None, "No data") and hrv not in (None, "No data"):
        return f"resting HR {rhr} and HRV {hrv} vs your baseline"
    if decision.rule == "stale_data" and facts.get("BASED_ON_DATE"):
        return f"sleep and HRV from {short_date(date.fromisoformat(facts['BASED_ON_DATE']))}"
    if facts.get("TRAINING_SESSIONS_7D", "").startswith("0 sessions"):
        return "no sessions in the last 7 days"
    ratio = facts.get("LOAD_RATIO")
    if ratio not in (None, "No data"):
        status = "above usual" if float(ratio) > 1.3 else "below usual" if float(ratio) < 0.8 else "normal"
        return f"load {ratio}, {status}"
    readiness = facts.get("READINESS")
    if readiness not in (None, "No data"):
        return f"readiness {readiness}"
    hard = facts.get("HARD_LAST_48H")
    if hard and any(char.isdigit() for char in hard):
        return hard
    if not getattr(decision, "provisional", True) and facts.get("BASED_ON_DATE"):
        return f"health data from {short_date(date.fromisoformat(facts['BASED_ON_DATE']))}"
    return ""


def morning(decision: Any, planned: list[str], ratio: float | None,
            unrated: tuple[int, str] | None = None,
            *, public_url: str = "", known_health_day: bool = True) -> OutboundMessage:
    waiting = decision.provisional or decision.rule == "stale_data"
    if waiting:
        title = f"{decision.intensity.title()} day — waiting for your data"
        if known_health_day:
            day = date.fromisoformat(decision.based_on)
            detail = f"Your latest sleep and HRV are from {short_date(day)}. "
        else:
            detail = "No recent sleep and HRV data. "
        lines = [title, detail + "Open Garmin Connect to sync your watch; I'll update you."]
    else:
        top = decision.sports[0] if decision.sports else None
        label = f"{top['session']['intent']} {'run' if top['sport'] == 'running' else top['sport']}" if top else "recovery"
        status = "normal" if ratio is not None and 0.8 <= ratio <= 1.3 else (
            "high" if ratio is not None and ratio > 1.3 else "low" if ratio is not None else "unavailable")
        ratio_text = f" ({ratio:.2f})" if ratio is not None else ""
        readiness = str(round(decision.readiness)) if decision.readiness is not None else "No data"
        no_sessions = any(fact["id"] == "TRAINING_SESSIONS_7D" and fact["display"].startswith("0 sessions")
                          for fact in getattr(decision, "facts", ()))
        lines = [f"{decision.intensity.title()} day — {label}",
                 f"Readiness {readiness} · " + ("no sessions in the last 7 days" if no_sessions else
                                              f"load {status}{ratio_text}")]
    session_text = _top_session(decision)
    if session_text:
        lines.append(session_text)
    if not waiting:
        hard_plan = any(word in item.lower() for item in planned
                        for word in ("tempo", "race", "match", "training", "strength"))
        adjustment = (" — rest instead" if decision.intensity == "rest" else
                      " — take it easy instead" if decision.intensity == "easy" else "") if hard_plan else ""
        lines.append("Planned: " + (" · ".join(planned) if planned else "nothing planned") + adjustment)
    if unrated:
        lines.append(f"How hard was {unrated[1]}?")
    keyboard = list(rating_keyboard([unrated] if unrated else []))
    link = public_link(public_url, "/")
    if link:
        keyboard.append(({"text": "Open Today", "url": link},))
    return _render(lines, tuple(keyboard))


def data_update(headline: str, reason: str | None = None, *, illness: bool = False) -> OutboundMessage:
    if reason:
        line = f"Data is in. {headline.rstrip('.')}: {reason}."
    else:
        line = f"Data is in. {headline}"
    if illness:
        line += " If this persists, see a doctor."
    return _render([line])


def proposal_items(changes: list[dict[str, Any]]) -> str:
    """Summarize at most four actual proposed edits, not a model-written summary."""
    result = []
    for change in changes[:4]:
        item = change["session"]
        day = date.fromisoformat(item["date"])
        sport = "run" if item["sport"] == "running" else item["sport"]
        label = f"{item['intent']} {sport} {item['duration_min']} min {day:%a}"
        if change["change_type"] == "remove":
            label = "remove " + label
        result.append(label)
    return " · ".join(result)


def day_review(day: date, done: list[str], skipped: list[str], unrated: list[tuple[int, str]],
               tomorrow: list[str], outlook: str, reason: str,
               *, public_url: str = "") -> OutboundMessage:
    future = " · ".join(tomorrow) if tomorrow else "nothing planned"
    outlook_line = f"outlook {outlook}" + (f" ({reason})" if reason else "")
    lines = [f"{short_date(day)} — day review"]
    if not done and not skipped:
        lines.append(f"Rest day today. Tomorrow: {future} · {outlook_line}")
    else:
        if done:
            lines.append("Done: " + " · ".join(done))
        lines.append("Skipped: " + (" · ".join(skipped) if skipped else "nothing"))
        for _, label in unrated[:2]:
            lines.append(f"How hard was {label}?")
        lines.append(f"Tomorrow: {future} · {outlook_line}")
    keyboard = list(rating_keyboard(unrated))
    link = public_link(public_url, "/plan")
    if link:
        keyboard.append(({"text": "Open Plan", "url": link},))
    return _render(lines, tuple(keyboard))


def weekly_review(start: date, actual: float, cap: float | None, done: int, planned: int,
                  mix: dict[str, int], trend: str, summary: str, proposal_id: int | None,
                  *, public_url: str = "") -> OutboundMessage:
    cap_text = f"{round(cap)}" if cap is not None else "no cap"
    sport_mix = " · ".join(f"{sport.title()} {count}" for sport, count in mix.items() if count)
    completion = f"{done} of {planned} planned sessions done" if planned else "no planned sessions"
    lines = [f"Week of {short_date(start)} — review",
             f"Load {round(actual)} of {cap_text} · {completion}"]
    if sport_mix:
        lines.append("Mix: " + sport_mix)
    if trend:
        lines.append(trend)
    lines.append("Next week: " + summary.strip().rstrip("."))
    keyboard: list[tuple[dict[str, str], ...]] = []
    if proposal_id is not None:
        keyboard.append(({"text": "Apply all", "callback_data": f"proposal:{proposal_id}:apply"},
                         {"text": "Dismiss", "callback_data": f"proposal:{proposal_id}:dismiss"}))
    link = public_link(public_url, "/plan")
    if link:
        keyboard.append(({"text": "Review in app", "url": link},))
    return _render(lines, tuple(keyboard))
