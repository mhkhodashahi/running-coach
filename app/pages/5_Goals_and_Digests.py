"""Goals and digest history page."""

from __future__ import annotations

from datetime import date

import streamlit as st

from analytics.performance import GOAL_RACE_DISTANCES, goal_time_minutes
from db import repository
from db.session import session_scope
from services.goal_service import GoalService
from utils.bootstrap import load_training_bundle
from utils.formatting import format_goal_time, format_pace

st.title("Goals and Digests")

bundle = load_training_bundle()
snapshot = bundle.snapshot
goal_service = GoalService()

active_goal = bundle.goals.loc[bundle.goals["is_active"].astype(bool)].head(1) if not bundle.goals.empty else bundle.goals
if not active_goal.empty:
    row = active_goal.iloc[0]
    projection = snapshot.get("active_goal_projection") or {}
    st.subheader("Active Goal")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Goal", row["name"])
    c2.metric("Target", format_goal_time(float(row["target_time_minutes"])))
    c3.metric("Distance", f"{float(row['target_distance_km']):.1f} km")
    c4.metric("Priority", row["priority"])
    if projection:
        c5, c6, c7 = st.columns(3)
        c5.metric("Target Pace", format_pace(float(projection["target_pace"])))
        c6.metric("Predicted Time", format_goal_time(float(projection["predicted_time_minutes"])))
        c7.metric("Gap", f"{float(projection['gap_minutes']):+.1f} min")
else:
    st.info("No goal configured yet. Create one below.")

st.subheader("Create Goal")
with st.form("create_goal_form"):
    goal_options = goal_service.supported_goal_types()
    labels = [label for _, label, _ in goal_options]
    selected_label = st.selectbox("Goal type", options=labels)
    selected_goal_type = next(goal_type for goal_type, label, _ in goal_options if label == selected_label)
    default_distance = GOAL_RACE_DISTANCES[selected_goal_type]
    goal_name = st.text_input("Goal name", value=f"My {selected_label}")
    target_time = st.text_input("Target time (HH:MM:SS)", value="03:59:59" if "Running" in selected_label else "00:21:30")
    target_distance_km = st.number_input(
        "Target distance (km)",
        min_value=1.0,
        max_value=100.0,
        value=float(default_distance),
        step=0.1,
    )
    target_date = st.date_input("Target date", value=date.today())
    priority = st.selectbox("Priority", options=["A", "B", "C"], index=0)
    notes = st.text_area("Notes", placeholder="Race name, course profile, or focus block notes.")
    make_active = st.checkbox("Set as active goal", value=True)
    submit_goal = st.form_submit_button("Save goal")

if submit_goal:
    try:
        target_time_minutes = float(goal_time_minutes(target_time))
    except Exception:
        st.error("Target time must use HH:MM:SS format.")
    else:
        with session_scope() as session:
            user = repository.get_or_create_default_user(session, bundle.user.id)
            repository.create_goal(
                session=session,
                user_id=user.id,
                payload={
                    "name": goal_name,
                    "goal_type": selected_goal_type,
                    "target_distance_km": float(target_distance_km),
                    "target_time_minutes": target_time_minutes,
                    "target_date": target_date,
                    "priority": priority,
                    "status": "active" if make_active else "planned",
                    "is_active": make_active,
                    "notes": notes.strip() or None,
                },
            )
        st.success("Goal saved.")
        st.rerun()

if not bundle.goals.empty:
    st.subheader("Goal List")
    st.dataframe(
        bundle.goals[
            ["id", "name", "goal_type", "target_distance_km", "target_time_minutes", "target_date", "priority", "status", "is_active"]
        ],
        width="stretch",
    )
    goal_options = {
        f"{row.id} | {row.name} | {row.goal_type}": int(row.id)
        for row in bundle.goals.itertuples()
    }
    selected_goal_label = st.selectbox("Choose goal to activate", list(goal_options.keys()))
    if st.button("Set selected goal active"):
        with session_scope() as session:
            repository.set_active_goal(session, bundle.user.id, goal_options[selected_goal_label])
        st.success("Active goal updated.")
        st.rerun()

st.subheader("Digest History")
if bundle.coaching_history.empty:
    st.caption("No coaching digest history yet.")
else:
    history_df = bundle.coaching_history[
        ["decision_date", "decision_type", "summary", "risk_level", "email_subject", "created_at"]
    ].rename(columns={"email_subject": "telegram_title"})
    st.dataframe(
        history_df,
        width="stretch",
    )

st.subheader("Telegram Delivery History")
if bundle.email_history.empty:
    st.caption("No coaching Telegram messages have been sent yet.")
else:
    st.dataframe(
        bundle.email_history[["sent_at", "recipient", "subject", "status", "provider_message"]],
        width="stretch",
    )
