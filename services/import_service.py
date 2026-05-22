"""Import and seed services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from config import get_settings
from db import repository
from services.garmin_client import CSVGarminClient, GarminAPIClient, GarminClient
from services.garmin_models import validate_laps, validate_track_points
from services.prediction_snapshot_service import PredictionSnapshotService


@dataclass
class ImportSummary:
    """Result of an import operation."""

    activities_imported: int = 0
    health_rows_imported: int = 0
    track_points_imported: int = 0
    laps_imported: int = 0
    prediction_snapshots_stored: int = 0


class GarminImportService:
    """Service for importing Garmin exports into the local database."""

    def __init__(self, client: GarminClient | None = None) -> None:
        self.client = client or CSVGarminClient()

    def import_files(
        self,
        session,
        user_id: int,
        activities_source: str | Path | BinaryIO | None = None,
        health_source: str | Path | BinaryIO | None = None,
    ) -> ImportSummary:
        summary = ImportSummary()

        if activities_source is not None:
            activity_rows = self.client.load_activities(activities_source, user_id)
            summary.activities_imported = repository.bulk_upsert_activities(session, activity_rows)
            user = repository.get_or_create_default_user(session, user_id)
            summary.prediction_snapshots_stored = PredictionSnapshotService().store_for_latest_runs(
                session,
                user=user,
                limit=len(activity_rows) or None,
            )

        if health_source is not None:
            health_rows = self.client.load_health_metrics(health_source, user_id)
            summary.health_rows_imported = repository.bulk_upsert_health_metrics(session, health_rows)

        return summary

    def seed_demo_data(self, session, user_id: int) -> ImportSummary:
        """Load bundled mock Garmin data when the database is empty."""

        settings = get_settings()
        return self.import_files(
            session=session,
            user_id=user_id,
            activities_source=settings.mock_activities_path,
            health_source=settings.mock_health_path,
        )

    def sync_garmin(
        self,
        session,
        user_id: int,
        days: int | None = None,
        health_days: int | None = None,
        include_activities: bool = True,
        include_health: bool = True,
        include_activity_details: bool = True,
    ) -> ImportSummary:
        """Sync recent activities and health metrics directly from Garmin Connect."""

        settings = get_settings()
        client = GarminAPIClient(
            email=settings.garmin_email,
            password=settings.garmin_password,
            token_dir=settings.garmin_token_dir,
            rate_limit_cooldown_minutes=settings.garmin_rate_limit_cooldown_minutes,
        )
        activity_rows, health_rows = client.sync_recent_data(
            user_id=user_id,
            days=days or settings.garmin_sync_days,
            health_days=health_days or settings.garmin_health_sync_days,
        )
        activities_imported = repository.bulk_upsert_activities(session, activity_rows) if include_activities else 0
        track_points_imported = 0
        laps_imported = 0
        if include_activities and include_activity_details and activity_rows:
            external_ids = [str(row["external_id"]) for row in activity_rows if row.get("external_id")]
            activity_id_map = repository.activity_ids_by_external_id(session, user_id, external_ids)
            detail_rows = client.sync_activity_details(user_id=user_id, activity_rows=activity_rows)
            for external_id, payload in detail_rows.items():
                activity_id = activity_id_map.get(str(external_id))
                if not activity_id:
                    continue
                if payload.get("track_points"):
                    track_points_imported += repository.replace_activity_track_points(
                        session,
                        activity_id,
                        validate_track_points(payload["track_points"]),
                    )
                if payload.get("laps"):
                    laps_imported += repository.replace_activity_laps(
                        session,
                        activity_id,
                        validate_laps(payload["laps"]),
                    )

        return ImportSummary(
            activities_imported=activities_imported,
            health_rows_imported=repository.bulk_upsert_health_metrics(session, health_rows) if include_health else 0,
            track_points_imported=track_points_imported,
            laps_imported=laps_imported,
            prediction_snapshots_stored=(
                PredictionSnapshotService().store_for_latest_runs(
                    session,
                    user=repository.get_or_create_default_user(session, user_id),
                    limit=len(activity_rows) or None,
                )
                if include_activities and activity_rows
                else 0
            ),
        )
