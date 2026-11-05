"""Persistence operations for Garmin sync status."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from db.models import GarminSyncStatus


class GarminSyncRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, user_id: int) -> GarminSyncStatus | None:
        return self._session.get(GarminSyncStatus, user_id)

    def mark_night_details_backfilled(self, user_id: int, at: datetime) -> None:
        status = self.get(user_id)
        if status is None:
            raise ValueError("Garmin sync status is missing")
        status.night_details_backfilled_at = at
