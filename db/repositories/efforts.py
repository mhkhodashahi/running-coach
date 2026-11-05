"""Persistence boundary for athlete effort ratings and delivery prompts."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from db.models import Activity, ActivityEffort, ActivityEffortPrompt


class EffortRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def activity(self, activity_id: int, user_id: int) -> Activity | None:
        return self._session.scalar(select(Activity).where(Activity.id == activity_id,
                                                          Activity.user_id == user_id))

    def activity_by_id(self, activity_id: int) -> Activity | None:
        return self._session.get(Activity, activity_id)

    def rating(self, activity_id: int) -> ActivityEffort | None:
        return self._session.get(ActivityEffort, activity_id)

    def activity_time(self, activity: Activity) -> str | None:
        stamp = self._session.execute(text(
            "SELECT MIN(start_time) FROM activity_laps WHERE activity_id=:id"), {"id": activity.id}).scalar()
        stamp = stamp or self._session.execute(text(
            "SELECT MIN(timestamp) FROM activity_track_points WHERE activity_id=:id"),
            {"id": activity.id}).scalar()
        return stamp

    def unrated_between(self, user_id: int, start: date, end: date) -> list[Activity]:
        return list(self._session.scalars(
            select(Activity).outerjoin(ActivityEffort, Activity.id == ActivityEffort.activity_id)
            .where(Activity.user_id == user_id, ActivityEffort.activity_id.is_(None),
                   Activity.date >= start, Activity.date <= end)
            .order_by(Activity.date.desc(), Activity.id.desc())).all())

    def prompt_ids(self) -> set[int]:
        return set(self._session.scalars(select(ActivityEffortPrompt.activity_id)).all())

    def prompt(self, activity_id: int) -> ActivityEffortPrompt | None:
        return self._session.get(ActivityEffortPrompt, activity_id)

    def add_rating(self, activity_id: int) -> ActivityEffort:
        rating = ActivityEffort(activity_id=activity_id)
        self._session.add(rating)
        return rating

    def add_prompt(self, activity_id: int) -> None:
        self._session.add(ActivityEffortPrompt(activity_id=activity_id))
