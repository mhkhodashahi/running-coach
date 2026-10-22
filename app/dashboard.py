"""Main Streamlit dashboard for the running coach app."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from config import get_settings
from services.coaching_engine import build_rule_recommendations
from services.daily_decision_service import get_or_create_daily_decision, set_athlete_choice
from services.training_context_service import load_training_bundle
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
    render_dashboard_hero,
    render_focus_cards,
    render_overview_metrics,
    render_today_status,
    render_warning_list,
)
from ui.sidebar import render_sidebar_menu
from utils.formatting import format_goal_time, format_pace

DASHBOARD_CHART_MONTHS = 3


def _latest_date(dataframe: pd.DataFrame, column: str) -> pd.Timestamp | None:
    if dataframe.empty or column not in dataframe:
        return None
    dates = pd.to_datetime(dataframe[column], errors="coerce").dropna()
    if dates.empty:
        return None
    return dates.max()


def _latest_dashboard_chart_date(
    snapshot: dict,
    activities: pd.DataFrame,
    health_metrics: pd.DataFrame,
    predictions: pd.DataFrame,
) -> pd.Timestamp | None:
    candidates = [
        _latest_date(activities, "date"),
        _latest_date(health_metrics, "date"),
        _latest_date(predictions, "prediction_date"),
        _latest_date(snapshot["weekly_mileage"]["weekly_series"], "week"),
        _latest_date(snapshot["training_load"], "date"),
    ]
    valid = [candidate for candidate in candidates if candidate is not None]
    return max(valid) if valid else None


def _filter_last_months(
    dataframe: pd.DataFrame,
    date_column: str,
    latest_date: pd.Timestamp | None,
    months: int = DASHBOARD_CHART_MONTHS,
) -> pd.DataFrame:
    if dataframe.empty or latest_date is None or date_column not in dataframe:
        return dataframe.copy()
    filtered = dataframe.copy()
    filtered[date_column] = pd.to_datetime(filtered[date_column], errors="coerce")
    cutoff = latest_date - pd.DateOffset(months=months)
    return filtered[filtered[date_column] >= cutoff].copy()


st.set_page_config(page_title="Running Coach", page_icon="R", layout="wide")
render_sidebar_menu()

bundle = load_training_bundle()
user = bundle.user
snapshot = bundle.snapshot
active_goal_projection = snapshot.get("active_goal_projection")
latest_chart_date = _latest_dashboard_chart_date(
    snapshot,
    bundle.activities,
    bundle.health_metrics,
    bundle.prediction_snapshots,
)
chart_activities = _filter_last_months(bundle.activities, "date", latest_chart_date)
chart_health_metrics = _filter_last_months(bundle.health_metrics, "date", latest_chart_date)
chart_prediction_snapshots = _filter_last_months(bundle.prediction_snapshots, "prediction_date", latest_chart_date)
chart_weekly_mileage = _filter_last_months(snapshot["weekly_mileage"]["weekly_series"], "week", latest_chart_date)
chart_training_load = _filter_last_months(snapshot["training_load"], "date", latest_chart_date)

hero_motivation = "Understand recovery, energy, and training load first. Then decide how running fits today."
render_dashboard_hero(user.name, hero_motivation)

render_today_status(snapshot)

st.subheader("Today's decision")
try:
    settings = get_settings()
    decision_day = datetime.now(ZoneInfo(settings.local_timezone)).date()
    daily_decision = get_or_create_daily_decision(decision_day, settings=settings, user_id=user.id)
    st.markdown(f"**{daily_decision.intensity.title()}** · Readiness "
                f"{daily_decision.readiness:.0f}/100" if daily_decision.readiness is not None else
                f"**{daily_decision.intensity.title()}** · Readiness: No data")
    if daily_decision.provisional:
        st.caption(f"Provisional · Based on {daily_decision.based_on} · Last sync {daily_decision.last_sync_time}")
    st.write(daily_decision.explanation)
    if daily_decision.sports:
        for item in daily_decision.sports:
            session = item["session"]
            cap = f", cap {session['hr_cap_bpm']} bpm" if isinstance(session["hr_cap_bpm"], int) else ""
            st.write(f"{item['rank']}. **{item['sport'].title()}**: {session['intent']}, "
                     f"{session['duration_min']} min{cap}. {item['reason']}.")
    elif daily_decision.optional:
        st.write(daily_decision.optional)
    if daily_decision.team_options:
        st.caption("Team sports")
        for option in daily_decision.team_options:
            st.write(f"{option['sport'].title()}: {option['label']}.")
    selected = st.selectbox("My intensity choice", ("Follow coach", "Rest", "Easy", "Hard"),
                            index=("Follow coach", "Rest", "Easy", "Hard").index(
                                daily_decision.athlete_choice.title() if daily_decision.athlete_choice else "Follow coach"),
                            key="today_intensity_override")
    choice = None if selected == "Follow coach" else selected.lower()
    if choice != daily_decision.athlete_choice:
        set_athlete_choice(decision_day, choice, settings=settings, user_id=user.id)
        st.caption("Your choice is saved separately from the coach decision.")
except (RuntimeError, ValueError) as exc:
    st.warning(f"Today's decision is unavailable: {exc}")

st.subheader("Health Snapshot")
render_overview_metrics(snapshot)
render_focus_cards(snapshot)

st.subheader("What Needs Attention")
render_warning_list(build_rule_recommendations(snapshot))

st.subheader("Health Trends")
col1, col2 = st.columns(2)
col1.plotly_chart(sleep_recovery_chart(chart_health_metrics), width="stretch")
col2.plotly_chart(vo2max_trend_chart(chart_health_metrics), width="stretch")

st.plotly_chart(vo2max_activity_chart(chart_health_metrics, chart_activities), width="stretch")

st.subheader("Training Balance")
col1, col2 = st.columns(2)
col1.plotly_chart(weekly_mileage_chart(chart_weekly_mileage), width="stretch")
col2.plotly_chart(training_load_chart(chart_training_load), width="stretch")

st.subheader("Running Fitness")
progress_col, log_col = st.columns([1.35, 1])
progress_col.plotly_chart(running_progress_chart(chart_activities), width="stretch")
log_col.plotly_chart(activity_calendar_chart(chart_activities), width="stretch")

st.subheader("Goal Check")
goal_prediction = active_goal_projection or snapshot["prediction"]
predicted_time = goal_prediction.get("predicted_time_minutes")
if predicted_time is None:
    predicted_time = goal_prediction["predicted_minutes"]
st.write(
    f"Goal pace is **{format_pace(snapshot['goal_pace'])}**. Current predicted pace is "
    f"**{format_pace(goal_prediction['predicted_pace'])}**, which maps to "
    f"**{format_goal_time(predicted_time)}**."
)
st.plotly_chart(goal_pace_chart(chart_activities, snapshot["goal_pace"]), width="stretch")
st.plotly_chart(prediction_snapshot_chart(chart_prediction_snapshots), width="stretch")

if not bundle.goals.empty:
    st.subheader("Goals")
    st.dataframe(
        bundle.goals[
            ["name", "goal_type", "target_distance_km", "target_time_minutes", "target_date", "priority", "status", "is_active"]
        ],
        width="stretch",
    )
