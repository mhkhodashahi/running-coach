"""Quality sessions page."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from services.training_context_service import load_training_bundle
from ui.components import apply_dashboard_theme

ANALYSIS_BLUE = "#2563eb"
ANALYSIS_GREEN = "#16a34a"
ANALYSIS_ORANGE = "#fc4c02"
ANALYSIS_INK = "#111827"
ANALYSIS_AMBER = "#f59e0b"
QUALITY_KEYWORDS = (
    "tempo",
    "threshold",
    "interval",
    "repetition",
    "rep",
    "fartlek",
    "race",
    "simulation",
    "progression",
    "speed",
)


def _running_activities(activities: pd.DataFrame) -> pd.DataFrame:
    if activities.empty:
        return activities.copy()
    runs = activities[
        activities["type"].fillna("").str.contains("run|trail|treadmill", case=False, na=False)
    ].copy()
    if runs.empty:
        return runs
    runs["date"] = pd.to_datetime(runs["date"])
    return runs.sort_values("date")


def _themed_figure(figure: go.Figure, title: str) -> go.Figure:
    figure.update_layout(
        title=title,
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.52)",
        font=dict(family="Manrope, sans-serif", color=ANALYSIS_INK),
        title_font=dict(size=20),
        margin=dict(l=34, r=28, t=58, b=38),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    figure.update_xaxes(gridcolor="rgba(100,116,139,0.16)", zeroline=False)
    figure.update_yaxes(gridcolor="rgba(100,116,139,0.16)", zeroline=False)
    return figure


def _quality_sessions_frame(runs: pd.DataFrame) -> pd.DataFrame:
    if runs.empty:
        return pd.DataFrame()

    sessions = runs.copy()
    median_pace = sessions["pace"].dropna().median()
    long_run_threshold = max(16.0, sessions["distance"].quantile(0.80))
    tempo_pace_threshold = median_pace * 0.94 if pd.notna(median_pace) else None
    text = sessions["notes"].fillna("").str.lower() + " " + sessions["type"].fillna("").str.lower()

    keyword_mask = text.str.contains("|".join(QUALITY_KEYWORDS), case=False, na=False)
    high_effect_mask = sessions["aerobic_effect"].fillna(0) >= 3.5
    anaerobic_mask = sessions["anaerobic_effect"].fillna(0) >= 1.0
    tempo_mask = pd.Series(False, index=sessions.index)
    if tempo_pace_threshold is not None:
        tempo_mask = (sessions["pace"].notna()) & (sessions["pace"] <= tempo_pace_threshold) & (sessions["distance"] >= 5)
    long_run_mask = sessions["distance"].fillna(0) >= long_run_threshold

    sessions["quality_score"] = (
        keyword_mask.astype(int) * 24
        + high_effect_mask.astype(int) * 24
        + anaerobic_mask.astype(int) * 22
        + tempo_mask.astype(int) * 18
        + long_run_mask.astype(int) * 12
        + sessions["distance"].fillna(0).clip(upper=25) * 0.8
    )
    sessions["is_quality"] = keyword_mask | high_effect_mask | anaerobic_mask | tempo_mask | long_run_mask
    quality = sessions[sessions["is_quality"]].copy()
    if quality.empty:
        return quality

    quality["quality_type"] = "Aerobic quality"
    quality.loc[long_run_mask.loc[quality.index], "quality_type"] = "Long run"
    quality.loc[tempo_mask.loc[quality.index], "quality_type"] = "Tempo"
    quality.loc[anaerobic_mask.loc[quality.index], "quality_type"] = "Intervals / speed"
    quality.loc[keyword_mask.loc[quality.index], "quality_type"] = "Tagged workout"

    reasons = []
    for index, row in quality.iterrows():
        row_reasons = []
        if keyword_mask.loc[index]:
            row_reasons.append("workout keyword")
        if high_effect_mask.loc[index]:
            row_reasons.append(f"aerobic effect {row.aerobic_effect:.1f}")
        if anaerobic_mask.loc[index]:
            row_reasons.append(f"anaerobic effect {row.anaerobic_effect:.1f}")
        if tempo_mask.loc[index]:
            row_reasons.append("faster than recent median pace")
        if long_run_mask.loc[index]:
            row_reasons.append("long-run distance")
        reasons.append(", ".join(row_reasons))
    quality["reason"] = reasons
    return quality.sort_values("date")


def _quality_volume_frame(runs: pd.DataFrame, quality: pd.DataFrame) -> pd.DataFrame:
    if runs.empty:
        return pd.DataFrame(columns=["week", "total_distance", "quality_distance", "quality_sessions"])
    weekly_total = (
        runs.set_index("date")["distance"]
        .resample("W-MON")
        .sum()
        .reset_index()
        .rename(columns={"date": "week", "distance": "total_distance"})
    )
    if quality.empty:
        weekly_total["quality_distance"] = 0.0
        weekly_total["quality_sessions"] = 0
        return weekly_total
    weekly_quality = (
        quality.set_index("date")
        .resample("W-MON")
        .agg(quality_distance=("distance", "sum"), quality_sessions=("id", "count"))
        .reset_index()
        .rename(columns={"date": "week"})
    )
    return weekly_total.merge(weekly_quality, on="week", how="left").fillna(
        {"quality_distance": 0.0, "quality_sessions": 0}
    )


def _quality_sessions_chart(volume: pd.DataFrame) -> go.Figure:
    figure = go.Figure()
    if volume.empty:
        return _themed_figure(figure, "Quality Sessions: Weekly Workload")
    figure.add_trace(
        go.Bar(
            x=volume["week"],
            y=volume["total_distance"],
            name="All running distance",
            marker_color="rgba(148, 163, 184, 0.42)",
            hovertemplate="Week=%{x|%b %d}<br>Total=%{y:.1f} km<extra></extra>",
        )
    )
    figure.add_trace(
        go.Bar(
            x=volume["week"],
            y=volume["quality_distance"],
            name="Quality-session distance",
            marker_color=ANALYSIS_BLUE,
            customdata=volume[["quality_sessions"]],
            hovertemplate=(
                "Week=%{x|%b %d}<br>Quality distance=%{y:.1f} km<br>"
                "Quality sessions=%{customdata[0]:.0f}<extra></extra>"
            ),
        )
    )
    _themed_figure(figure, "Quality Sessions: Weekly Workload")
    figure.update_layout(barmode="overlay", yaxis_title="Distance (km)")
    return figure


def _quality_type_chart(quality: pd.DataFrame) -> go.Figure:
    figure = go.Figure()
    if quality.empty:
        return _themed_figure(figure, "Quality Session Types")
    grouped = (
        quality.groupby("quality_type", as_index=False)
        .agg(distance=("distance", "sum"), sessions=("id", "count"))
        .sort_values("distance", ascending=True)
    )
    figure.add_trace(
        go.Bar(
            x=grouped["distance"],
            y=grouped["quality_type"],
            orientation="h",
            marker_color=[ANALYSIS_ORANGE, ANALYSIS_BLUE, ANALYSIS_GREEN, ANALYSIS_AMBER][: len(grouped)],
            customdata=grouped[["sessions"]],
            hovertemplate="%{y}<br>Distance=%{x:.1f} km<br>Sessions=%{customdata[0]}<extra></extra>",
        )
    )
    figure.update_xaxes(title="Distance (km)")
    return _themed_figure(figure, "Quality Session Types")


apply_dashboard_theme()
st.title("Quality Sessions")
st.caption(
    "Runalyze-inspired tempo-session review. Sessions are classified from pace, distance, effects, type, and notes."
)

bundle = load_training_bundle()
runs = _running_activities(bundle.activities)
if runs.empty:
    st.info("No running activities available yet. Import activities from the dashboard sidebar to unlock quality sessions.")
    st.stop()

quality_sessions = _quality_sessions_frame(runs)
quality_volume = _quality_volume_frame(runs, quality_sessions)
quality_distance = float(quality_sessions["distance"].sum()) if not quality_sessions.empty else 0.0
total_distance = max(float(runs["distance"].sum()), 1.0)
latest_quality = quality_sessions["date"].max().strftime("%Y-%m-%d") if not quality_sessions.empty else "n/a"

c1, c2, c3, c4 = st.columns(4)
c1.metric("Quality sessions", len(quality_sessions))
c2.metric("Quality distance", f"{quality_distance:.1f} km")
c3.metric("Quality share", f"{quality_distance / total_distance:.0%}")
c4.metric("Latest quality", latest_quality)

chart_col, type_col = st.columns([1.35, 1])
chart_col.plotly_chart(_quality_sessions_chart(quality_volume), width="stretch")
type_col.plotly_chart(_quality_type_chart(quality_sessions), width="stretch")

st.subheader("Detected Sessions")
if quality_sessions.empty:
    st.info("No quality sessions detected yet. Add notes like tempo, threshold, interval, fartlek, race, or progression to improve classification.")
else:
    table = quality_sessions.sort_values("date", ascending=False).copy()
    table["date"] = table["date"].dt.date
    st.dataframe(
        table[
            [
                "date",
                "quality_type",
                "distance",
                "duration",
                "pace",
                "avg_hr",
                "aerobic_effect",
                "anaerobic_effect",
                "quality_score",
                "reason",
            ]
        ],
        width="stretch",
    )

st.caption(
    "Classification is approximate because lap-level interval data is not stored yet. Add structured splits later for true interval-section analysis."
)
