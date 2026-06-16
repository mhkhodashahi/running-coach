"""Goal achievement readiness page."""

from __future__ import annotations

import streamlit as st

from services.training_context_service import load_training_bundle
from ui.charts import goal_pace_chart, intensity_distribution_chart, long_run_progression_chart
from ui.components import render_goal_summary
from utils.formatting import format_gap_minutes, format_goal_time, format_pace

st.title("Goal Achievement Readiness")
st.caption("See whether your current training is moving you toward the active race goal.")

bundle = load_training_bundle()
snapshot = bundle.snapshot
prediction = snapshot.get("active_goal_projection") or snapshot["prediction"]
predicted_finish_minutes = prediction.get("predicted_time_minutes")
if predicted_finish_minutes is None:
    predicted_finish_minutes = prediction["predicted_minutes"]

active_goal = None
if not bundle.goals.empty and "is_active" in bundle.goals:
    active_goals = bundle.goals.loc[bundle.goals["is_active"].astype(bool)]
    if not active_goals.empty:
        active_goal = active_goals.iloc[0]

if active_goal is not None:
    goal_name = str(active_goal["name"])
    goal_distance = float(active_goal["target_distance_km"])
    goal_label = f"{goal_name} ({goal_distance:.1f} km)"
else:
    goal_label = "default active goal"

st.subheader(f"Readiness for {goal_label}")
render_goal_summary(
    goal_pace=snapshot["goal_pace"],
    predicted_pace=prediction["predicted_pace"],
    predicted_finish_minutes=predicted_finish_minutes,
)

st.write(
    f"Gap to goal: **{format_gap_minutes(prediction['gap_minutes'])}**. "
    f"Goal achievement confidence: **{prediction['confidence']:.0f}%**."
)

col1, col2 = st.columns(2)
col1.plotly_chart(goal_pace_chart(bundle.activities, snapshot["goal_pace"]), width="stretch")
col2.plotly_chart(
    intensity_distribution_chart(snapshot["intensity"]["distribution"]),
    width="stretch",
)

st.plotly_chart(long_run_progression_chart(snapshot["long_runs"]["progression"]), width="stretch")

st.subheader("Goal Readiness Interpretation")
st.write(
    f"Weekly mileage is **{snapshot['weekly_mileage']['7d']:.1f} km** over the last 7 days and "
    f"**{snapshot['weekly_mileage']['28d']:.1f} km** over the last 28 days."
)
st.write(
    f"Latest long run: **{snapshot['long_runs']['latest_long_run_km']:.1f} km**. "
    f"Consistency score: **{snapshot['consistency']['score']:.0f}**. "
    f"Fatigue score: **{snapshot['fatigue']['score']:.0f}**."
)

st.subheader("Goal Scenario Widget")
widget_col1, widget_col2 = st.columns(2)
race_distance = widget_col1.slider("Goal distance (km)", min_value=5.0, max_value=42.2, value=21.1, step=0.1)
target_pace = widget_col2.slider(
    "Target pace (min/km)",
    min_value=4.0,
    max_value=7.5,
    value=float(prediction["predicted_pace"]),
    step=0.05,
)
predicted_time_minutes = race_distance * target_pace
st.write(
    f"Goal finish time for **{race_distance:.1f} km** at **{format_pace(target_pace)}**: "
    f"**{format_goal_time(predicted_time_minutes)}**."
)
