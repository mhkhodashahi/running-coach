"""Activities page."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ui.charts import hr_trend_chart, long_run_progression_chart, pace_trend_chart, weekly_mileage_chart
from ui.components import apply_dashboard_theme
from utils.bootstrap import load_training_bundle
from utils.formatting import format_duration_minutes, format_metric_number, format_pace

TYPE_COLORS = {
    "running": "#fc4c02",
    "run": "#fc4c02",
    "trail": "#f59e0b",
    "treadmill": "#ef4444",
    "cycling": "#2563eb",
    "walking": "#16a34a",
    "strength": "#7c3aed",
}


def _type_color(activity_type: str | None) -> str:
    normalized = str(activity_type or "").lower()
    for key, color in TYPE_COLORS.items():
        if key in normalized:
            return color
    return "#64748b"


def _activity_time(value: pd.Timestamp) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp.hour == 0 and timestamp.minute == 0:
        return "Time not stored"
    return timestamp.strftime("%H:%M")


def _render_activity_card(row) -> None:
    color = _type_color(row.type)
    activity_type = str(row.type or "activity").replace("_", " ").title()
    pace = format_pace(float(row.pace)) if pd.notna(row.pace) else "n/a"
    avg_hr = format_metric_number(row.avg_hr, decimals=0, suffix=" bpm")
    st.markdown(
        f"""
        <div class="activity-list-card" style="border-left-color:{color};">
            <div class="activity-list-top">
                <span class="activity-type-pill" style="background:{color};">{activity_type}</span>
                <span>{row.date:%A, %d %b %Y} · {_activity_time(row.date)}</span>
            </div>
            <div class="activity-list-title">{row.distance:.2f} km {activity_type}</div>
            <div class="activity-list-grid">
                <div><strong>{format_duration_minutes(float(row.duration))}</strong><span>Duration</span></div>
                <div><strong>{pace}</strong><span>Pace</span></div>
                <div><strong>{avg_hr}</strong><span>Avg HR</span></div>
                <div><strong>{format_metric_number(row.elevation, decimals=0, suffix=" m")}</strong><span>Elevation</span></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


apply_dashboard_theme()
st.title("Activities")
st.caption("Browse activities as cards. Open one to see the full Strava-inspired detail page.")

st.markdown(
    """
    <style>
        .activity-list-card {
            background: rgba(255, 255, 255, 0.86);
            border: 1px solid rgba(15, 23, 42, 0.10);
            border-left: 8px solid #fc4c02;
            border-radius: 24px;
            box-shadow: 0 18px 45px rgba(15, 23, 42, 0.08);
            padding: 18px 20px;
            margin-bottom: 8px;
        }
        .activity-list-top {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            color: #64748b;
            font-size: 0.86rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }
        .activity-type-pill {
            color: white;
            border-radius: 999px;
            padding: 4px 9px;
            font-size: 0.74rem;
            line-height: 1;
        }
        .activity-list-title {
            margin-top: 12px;
            color: #111827;
            font-size: 1.35rem;
            font-weight: 800;
            letter-spacing: -0.04em;
        }
        .activity-list-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(90px, 1fr));
            gap: 10px;
            margin-top: 14px;
        }
        .activity-list-grid div {
            background: rgba(248, 250, 252, 0.92);
            border-radius: 16px;
            padding: 10px;
        }
        .activity-list-grid strong {
            display: block;
            color: #111827;
            font-weight: 800;
        }
        .activity-list-grid span {
            color: #64748b;
            font-size: 0.76rem;
            font-weight: 800;
            text-transform: uppercase;
        }
        @media (max-width: 760px) {
            .activity-list-top {
                display: block;
            }
            .activity-list-grid {
                grid-template-columns: 1fr 1fr;
            }
        }
    </style>
    """,
    unsafe_allow_html=True,
)

bundle = load_training_bundle()
activities = bundle.activities.copy()

if activities.empty:
    st.info("No activities available yet. Import a CSV from the dashboard sidebar.")
else:
    min_date = activities["date"].min().date()
    max_date = activities["date"].max().date()
    selected_range = st.date_input("Date range", value=(min_date, max_date), min_value=min_date, max_value=max_date)
    selected_types = st.multiselect("Activity types", sorted(activities["type"].dropna().unique()), default=sorted(activities["type"].dropna().unique()))

    if len(selected_range) == 2:
        start_date, end_date = selected_range
        activities = activities[(activities["date"].dt.date >= start_date) & (activities["date"].dt.date <= end_date)]
    activities = activities[activities["type"].isin(selected_types)]

    st.subheader("Activity List")
    for row in activities.sort_values("date", ascending=False).itertuples():
        card_col, action_col = st.columns([5, 1])
        with card_col:
            _render_activity_card(row)
        with action_col:
            st.write("")
            st.write("")
            if st.button("View", key=f"view_activity_{row.id}", width="stretch"):
                st.session_state["selected_activity_id"] = int(row.id)
                st.switch_page("pages/8_Activity_Detail.py")

    col1, col2 = st.columns(2)
    col1.plotly_chart(weekly_mileage_chart(bundle.snapshot["weekly_mileage"]["weekly_series"]), width="stretch")
    col2.plotly_chart(pace_trend_chart(activities), width="stretch")

    col3, col4 = st.columns(2)
    col3.plotly_chart(hr_trend_chart(activities), width="stretch")
    col4.plotly_chart(long_run_progression_chart(bundle.snapshot["long_runs"]["progression"]), width="stretch")
