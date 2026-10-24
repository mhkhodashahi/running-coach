"""Shared navigation sidebar controls and data status."""

from __future__ import annotations

import streamlit as st

from config import get_settings
from db import repository
from db.session import session_scope
from services.effort_service import dispatch_effort_prompts
from services.import_service import GarminImportService
from services.telegram_service import TelegramService
from services.training_context_service import bootstrap_app
from ui.components import apply_dashboard_theme, render_sidebar_sync_status
from utils.formatting import format_goal_time


def render_sidebar_menu() -> None:
    apply_dashboard_theme()
    settings = get_settings()
    user = bootstrap_app()
    with session_scope() as session:
        user = repository.get_or_create_default_user(session, user.id)
        goals = repository.list_goals(session, user.id)
        last_garmin_sync = repository.get_last_garmin_sync(session, user.id)
        latest_activity_date = repository.latest_activity_date(session, user.id)

    with st.sidebar:
        with st.expander("Athlete Profile", expanded=False):
            with st.form("user_profile_form"):
                name = st.text_input("Name", value=user.name or "")
                age = st.number_input("Age", min_value=18, max_value=85, value=int(user.age or 34))
                gender_options = ["unspecified", "male", "female", "other"]
                gender = st.selectbox(
                    "Gender",
                    options=gender_options,
                    index=gender_options.index(user.gender) if user.gender in gender_options else 0,
                )
                weight = st.number_input("Weight (kg)", min_value=40.0, max_value=150.0, value=float(user.weight or 73.0), step=0.5)
                height = st.number_input("Height (cm)", min_value=140.0, max_value=220.0, value=float(user.height or 178.0), step=0.5)
                max_hr = st.number_input("Max HR", min_value=120, max_value=220, value=int(user.max_hr or 188))
                training_days_per_week = st.slider("Training days per week", min_value=1, max_value=7, value=int(user.training_days_per_week or 5))
                injury_notes = st.text_area("Injury notes", value=user.injury_notes or "", placeholder="Any niggles, restrictions, or recent injuries.")
                submit_profile = st.form_submit_button("Save profile")

        if submit_profile:
            with session_scope() as session:
                repository.update_user_profile(
                    session,
                    user.id,
                    {
                        "name": name.strip() or None,
                        "age": age,
                        "gender": gender,
                        "weight": weight,
                        "height": height,
                        "max_hr": max_hr,
                        "training_days_per_week": training_days_per_week,
                        "injury_notes": injury_notes.strip() or None,
                    },
                )
            st.success("Profile updated.")
            st.rerun()

        with st.expander("Active Goal", expanded=False):
            if goals:
                active_goal = next((goal for goal in goals if goal.is_active), goals[0])
                st.caption(active_goal.name)
                st.write(f"Type: {active_goal.goal_type}")
                st.write(
                    f"Target: {format_goal_time(active_goal.target_time_minutes)} "
                    f"over {active_goal.target_distance_km:.1f} km"
                )
                if active_goal.target_date:
                    st.write(f"Race date: {active_goal.target_date}")
            else:
                st.caption("No goal set yet.")

        with st.expander("CSV Import", expanded=False):
            with st.form("csv_import_form"):
                activities_file = st.file_uploader("Activities CSV", type="csv")
                health_file = st.file_uploader("Health Metrics CSV", type="csv")
                import_submit = st.form_submit_button("Import CSVs")

        if import_submit and (activities_file or health_file):
            importer = GarminImportService()
            with session_scope() as session:
                summary = importer.import_files(
                    session,
                    user_id=user.id,
                    activities_source=activities_file if activities_file else None,
                    health_source=health_file if health_file else None,
                )
            st.success(f"Imported {summary.activities_imported} activities and {summary.health_rows_imported} health rows.")
            st.rerun()

        with st.expander("Garmin Sync", expanded=False):
            with st.form("garmin_sync_form"):
                sync_days = st.number_input(
                    "Activity sync window (days)",
                    min_value=7,
                    max_value=365,
                    value=int(settings.garmin_sync_days),
                    step=7,
                )
                health_days = st.number_input(
                    "Health sync window (days)",
                    min_value=1,
                    max_value=60,
                    value=int(settings.garmin_health_sync_days),
                    step=1,
                    help="Health metrics use daily Garmin requests, so keep this window shorter than activities.",
                )
                sync_submit = st.form_submit_button("Sync from Garmin")

        if sync_submit:
            if not settings.garmin_email or not settings.garmin_password:
                st.error("Add GARMIN_EMAIL and GARMIN_PASSWORD to .env before using live Garmin sync.")
            else:
                importer = GarminImportService()
                try:
                    with st.spinner("Syncing Garmin data..."):
                        with session_scope() as session:
                            summary = importer.sync_garmin(
                                session=session,
                                user_id=user.id,
                                days=int(sync_days),
                                health_days=int(health_days),
                            )
                    st.success(
                        f"Synced {summary.activities_imported} activities, "
                        f"{summary.track_points_imported} GPS points, "
                        f"{summary.laps_imported} laps, and "
                        f"{summary.health_rows_imported} health rows from Garmin."
                    )
                    try:
                        dispatch_effort_prompts(settings, user.id, TelegramService(settings))
                    except Exception as exc:
                        st.warning(f"Activities synced, but the effort prompt could not be sent: {exc}")
                    else:
                        st.rerun()
                except Exception as exc:
                    st.error(f"Garmin sync failed: {exc}")

        render_sidebar_sync_status(last_garmin_sync, latest_activity_date)
