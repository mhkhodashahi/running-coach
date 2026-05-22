from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db import repository
from db.models import Base
from services.prediction_snapshot_service import PredictionSnapshotService


def test_prediction_snapshot_is_stored_for_each_run() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)

    with session_factory() as session:
        user = repository.get_or_create_default_user(session, 1)
        repository.get_or_create_default_goal(session, user)
        repository.bulk_upsert_activities(
            session,
            [
                {
                    "user_id": user.id,
                    "external_id": "run-1",
                    "date": date(2026, 5, 20),
                    "type": "running",
                    "distance": 8.0,
                    "duration": 48.0,
                    "pace": 6.0,
                },
                {
                    "user_id": user.id,
                    "external_id": "walk-1",
                    "date": date(2026, 5, 21),
                    "type": "walking",
                    "distance": 4.0,
                    "duration": 50.0,
                    "pace": 12.5,
                },
                {
                    "user_id": user.id,
                    "external_id": "run-2",
                    "date": date(2026, 5, 22),
                    "type": "running",
                    "distance": 10.0,
                    "duration": 55.0,
                    "pace": 5.5,
                },
            ],
        )

        stored = PredictionSnapshotService().store_for_latest_runs(session, user=user)
        snapshots = repository.prediction_snapshots_dataframe(session, user.id)

    assert stored == 2
    assert len(snapshots) == 2
    assert set(snapshots["activity_type"]) == {"running"}
    assert snapshots["predicted_time_minutes"].notna().all()
