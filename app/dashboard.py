"""Main Streamlit dashboard for the running coach app."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from config import get_settings
from db import repository
from db.session import session_scope
from services.coaching_engine import build_rule_recommendations
from services.import_service import GarminImportService
from ui.charts import (
    activity_calendar_chart,
    goal_pace_chart,
    prediction_snapshot_chart,
    running_progress_chart,
    sleep_recovery_chart,
    training_load_chart,
    vo2max_activity_chart,
    vo2max_trend_chart,
    weekly_mileage_chart,
)
from ui.components import (
    apply_dashboard_theme,
    render_dashboard_hero,
    render_focus_cards,
    render_overview_metrics,
    render_warning_list,
)
from utils.bootstrap import load_training_bundle
from utils.formatting import format_gap_minutes, format_goal_time, format_pace

st.set_page_config(page_title="Running Coach", page_icon="R", layout="wide")
apply_dashboard_theme()

settings = get_settings()
bundle = load_training_bundle()
user = bundle.user
snapshot = bundle.snapshot
active_goal_projection = snapshot.get("active_goal_projection")

hero_motivation = (
    "Track the same things that move race fitness: weekly distance, monthly consistency, "
    "long-run durability, and recovery readiness."
)
render_dashboard_hero(user.name, hero_motivation)

with st.sidebar:
    st.header("Athlete Profile")
    with st.form("user_profile_form"):
        name = st.text_input("Name", value=user.name or "")
        age = st.number_input("Age", min_value=18, max_value=85, value=int(user.age or 34))
        gender = st.selectbox("Gender", options=["male", "female", "other"], index=["male", "female", "other"].index(user.gender or "male"))
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

    if not bundle.goals.empty:
        st.header("Active Goal")
        active_goal = bundle.goals.loc[bundle.goals["is_active"].astype(bool)].head(1)
        if active_goal.empty:
            active_goal = bundle.goals.head(1)
        row = active_goal.iloc[0]
        st.caption(row["name"])
        st.write(f"Type: {row['goal_type']}")
        st.write(f"Target: {format_goal_time(row['target_time_minutes'])} over {row['target_distance_km']:.1f} km")
        if pd.notna(row["target_date"]):
            st.write(f"Race date: {row['target_date'].date()}")

    st.header("CSV Import")
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
        st.success(
            f"Imported {summary.activities_imported} activities and {summary.health_rows_imported} health rows."
        )
        st.rerun()

    st.header("Garmin Sync")
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
                st.rerun()
            except Exception as exc:
                st.error(f"Garmin sync failed: {exc}")

render_overview_metrics(snapshot)
render_focus_cards(snapshot)

st.subheader("Coaching Alerts")
render_warning_list(build_rule_recommendations(snapshot))

if active_goal_projection:
    st.subheader("Active Goal Projection")
    g1, g2, g3, g4 = st.columns(4)
    g1.metric("Goal Pace", format_pace(active_goal_projection["target_pace"]))
    g2.metric("Predicted Pace", format_pace(active_goal_projection["predicted_pace"]))
    g3.metric("Predicted Time", format_goal_time(active_goal_projection["predicted_time_minutes"]))
    g4.metric("Gap", format_gap_minutes(active_goal_projection["gap_minutes"]))

st.subheader("Running Progress")
progress_col, log_col = st.columns([1.35, 1])
progress_col.plotly_chart(running_progress_chart(bundle.activities), width="stretch")
log_col.plotly_chart(activity_calendar_chart(bundle.activities), width="stretch")

st.subheader("Prediction Trend")
st.plotly_chart(prediction_snapshot_chart(bundle.prediction_snapshots), width="stretch")

col1, col2 = st.columns(2)
col1.plotly_chart(weekly_mileage_chart(snapshot["weekly_mileage"]["weekly_series"]), width="stretch")
col2.plotly_chart(vo2max_trend_chart(bundle.health_metrics), width="stretch")

col3, col4 = st.columns(2)
col3.plotly_chart(sleep_recovery_chart(bundle.health_metrics), width="stretch")
col4.plotly_chart(training_load_chart(snapshot["training_load"]), width="stretch")

st.plotly_chart(vo2max_activity_chart(bundle.health_metrics, bundle.activities), width="stretch")

st.subheader("Goal Progress")
goal_prediction = active_goal_projection or snapshot["prediction"]
predicted_time = goal_prediction.get("predicted_time_minutes")
if predicted_time is None:
    predicted_time = goal_prediction["predicted_minutes"]
st.write(
    f"Goal pace is **{format_pace(snapshot['goal_pace'])}**. Current predicted pace is "
    f"**{format_pace(goal_prediction['predicted_pace'])}**, which maps to "
    f"**{format_goal_time(predicted_time)}**."
)
st.plotly_chart(goal_pace_chart(bundle.activities, snapshot["goal_pace"]), width="stretch")

if not bundle.goals.empty:
    st.subheader("Goals")
    st.dataframe(
        bundle.goals[
            ["name", "goal_type", "target_distance_km", "target_time_minutes", "target_date", "priority", "status", "is_active"]
        ],
        width="stretch",
    )
