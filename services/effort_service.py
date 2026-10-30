"""Latest effort ratings and durable one-time rating prompts."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from db.models import Activity, ActivityEffort, ActivityEffortPrompt
from metrics.sports import sport_category

REMINDER_DELAY = timedelta(hours=12)
RATING_PROMPT_WINDOW = timedelta(hours=48)
CR10_LABELS = {0: "rest", 3: "moderate", 5: "hard", 7: "very hard", 10: "maximal"}


def rate_activity(session: Session, activity_id: int, user_id: int, rpe: int, source: str,
                  note: str | None = None, now: datetime | None = None) -> ActivityEffort:
    if isinstance(rpe, bool) or not isinstance(rpe, int) or not 0 <= rpe <= 10:
        raise ValueError("RPE must be an integer from 0 to 10")
    if source not in ("web", "telegram"):
        raise ValueError("Unknown rating source")
    activity = session.scalar(select(Activity).where(Activity.id == activity_id, Activity.user_id == user_id))
    if activity is None:
        raise ValueError("Activity not found")
    if sport_category(activity.type, activity.date) in ("excluded", "mobility") or activity.type.strip().lower() == "walking":
        raise ValueError("This activity is not rateable")
    effort = session.get(ActivityEffort, activity_id)
    if effort is None:
        effort = ActivityEffort(activity_id=activity_id)
        session.add(effort)
    effort.rpe = rpe
    effort.rated_at = (now or datetime.now(UTC)).replace(tzinfo=None)
    effort.source = source
    effort.note = note
    session.flush()
    return effort


def _activity_time(session: Session, activity: Activity, timezone: str) -> datetime:
    stamp = session.execute(text(
        "SELECT MIN(start_time) FROM activity_laps WHERE activity_id=:id"), {"id": activity.id}).scalar()
    stamp = stamp or session.execute(text(
        "SELECT MIN(timestamp) FROM activity_track_points WHERE activity_id=:id"), {"id": activity.id}).scalar()
    zone = ZoneInfo(timezone)
    if stamp:
        parsed = datetime.fromisoformat(stamp)
        return parsed.replace(tzinfo=zone) if parsed.tzinfo is None else parsed.astimezone(zone)
    return datetime.combine(activity.date, time.min, zone)


def unrated_activities(session: Session, user_id: int, limit: int = 5, *,
                       now: datetime | None = None, timezone: str = "Europe/Berlin") -> list[Activity]:
    """Shared Today and Telegram selector; never prompt outside the last 48 hours."""
    zone = ZoneInfo(timezone)
    local_now = now or datetime.now(UTC)
    local_now = local_now.replace(tzinfo=zone) if local_now.tzinfo is None else local_now.astimezone(zone)
    cutoff_date = (local_now.astimezone(UTC) - RATING_PROMPT_WINDOW).astimezone(zone).date()
    rows = session.scalars(select(Activity).outerjoin(ActivityEffort, Activity.id == ActivityEffort.activity_id)
                           .where(Activity.user_id == user_id, ActivityEffort.activity_id.is_(None),
                                  Activity.date >= cutoff_date,
                                  Activity.date <= local_now.date())
                           .order_by(Activity.date.desc(), Activity.id.desc())).all()
    eligible = [(row, _activity_time(session, row, timezone)) for row in rows
                if sport_category(row.type, row.date) not in ("excluded", "mobility")
                and row.type.strip().lower() != "walking"]
    eligible = [(row, started) for row, started in eligible
                if timedelta(0) <= local_now.astimezone(UTC) - started.astimezone(UTC) <= RATING_PROMPT_WINDOW]
    eligible.sort(key=lambda item: (item[1].astimezone(UTC), item[0].id), reverse=True)
    return [row for row, _ in eligible[:limit]]


def prompt_candidates(session: Session, user_id: int, now: datetime,
                      timezone: str = "Europe/Berlin") -> list[tuple[Activity, bool]]:
    eligible = unrated_activities(session, user_id, limit=100, now=now, timezone=timezone)
    now = now.replace(tzinfo=None)
    result = []
    pending_ids = set(session.scalars(select(ActivityEffortPrompt.activity_id)).all())
    for activity in eligible:
        if activity.id not in pending_ids:
            continue
        prompt = session.get(ActivityEffortPrompt, activity.id)
        if prompt.sent_at is None:
            result.append((activity, False))
        elif prompt.reminded_at is None and now - prompt.sent_at >= REMINDER_DELAY:
            result.append((activity, True))
    return result


def mark_prompt_sent(session: Session, activity_id: int, reminder: bool, now: datetime) -> None:
    now = now.replace(tzinfo=None)
    prompt = session.get(ActivityEffortPrompt, activity_id)
    if reminder:
        if prompt is None or prompt.reminded_at is not None or now - prompt.sent_at < REMINDER_DELAY:
            raise ValueError("Reminder is not due")
        prompt.reminded_at = now
    elif prompt is not None and prompt.sent_at is None:
        prompt.sent_at = now
    else:
        raise ValueError("Initial prompt is not pending")


def queue_new_activities(session: Session, activity_ids: set[int]) -> None:
    for activity_id in activity_ids:
        activity = session.get(Activity, activity_id)
        if activity is None or sport_category(activity.type, activity.date) in ("excluded", "mobility"):
            continue
        if activity.type.strip().lower() == "walking":
            continue
        if session.get(ActivityEffortPrompt, activity_id) is None:
            session.add(ActivityEffortPrompt(activity_id=activity_id))


def dispatch_effort_prompts(settings: object, user_id: int, telegram: object) -> int:
    """Send each queued prompt once and one reminder after twelve hours."""
    from db.session import session_scope

    if not telegram.configured:
        return 0
    sent = 0
    with session_scope() as session:
        for activity, reminder in prompt_candidates(session, user_id, datetime.now(UTC),
                                                    settings.local_timezone):
            first = session.execute(text(
                "SELECT MIN(start_time) FROM activity_laps WHERE activity_id=:id"),
                {"id": activity.id}).scalar()
            first = first or session.execute(text(
                "SELECT MIN(timestamp) FROM activity_track_points WHERE activity_id=:id"),
                {"id": activity.id}).scalar()
            clock = " time unavailable"
            if first:
                stamp = datetime.fromisoformat(first)
                zone = ZoneInfo(settings.local_timezone)
                stamp = stamp.replace(tzinfo=zone) if stamp.tzinfo is None else stamp.astimezone(zone)
                clock = " " + stamp.strftime("%H:%M")
            when = activity.date.strftime("%d %b %Y") + clock
            message = f"How hard was {sport_category(activity.type, activity.date)} {when}? 0–10"
            message += "\nCR-10: 0 rest · 3 moderate · 5 hard · 7 very hard · 10 maximal"
            if reminder:
                message = "Reminder: " + message
            mark_prompt_sent(session, activity.id, reminder, datetime.now(UTC))
            session.commit()
            telegram.send_rating_prompt(message, activity.id)
            sent += 1
    return sent
