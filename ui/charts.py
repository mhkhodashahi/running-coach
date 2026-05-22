"""Plotly chart builders."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

STRAVA_ORANGE = "#fc4c02"
DEEP_INK = "#111827"
AMBER = "#ffb000"
GREEN = "#22c55e"


def _apply_chart_theme(figure: go.Figure, title: str | None = None) -> go.Figure:
    figure.update_layout(
        title=title,
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.38)",
        font=dict(family="Manrope, sans-serif", color=DEEP_INK),
        title_font=dict(size=20, color=DEEP_INK),
        margin=dict(l=32, r=28, t=58, b=36),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    figure.update_xaxes(gridcolor="rgba(100,116,139,0.14)", zeroline=False)
    figure.update_yaxes(gridcolor="rgba(100,116,139,0.14)", zeroline=False)
    return figure


def _empty_figure(title: str, message: str = "No data available yet.") -> go.Figure:
    figure = go.Figure()
    _apply_chart_theme(figure, title)
    figure.add_annotation(text=message, x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False)
    return figure


def _running_activities(activities_df: pd.DataFrame) -> pd.DataFrame:
    if activities_df.empty:
        return activities_df.copy()
    runs = activities_df[
        activities_df["type"].fillna("").str.contains("run|trail|treadmill", case=False, na=False)
    ].copy()
    if not runs.empty:
        runs["date"] = pd.to_datetime(runs["date"])
        runs = runs.sort_values("date")
    return runs


def weekly_mileage_chart(weekly_series: pd.DataFrame) -> go.Figure:
    if weekly_series.empty:
        return _empty_figure("Weekly Mileage")
    figure = px.bar(
        weekly_series,
        x="week",
        y="distance",
        title="Weekly Mileage",
        labels={"distance": "km"},
        color_discrete_sequence=[STRAVA_ORANGE],
    )
    figure.update_traces(marker_line_width=0, opacity=0.92, hovertemplate="Week=%{x|%b %d}<br>Distance=%{y:.1f} km<extra></extra>")
    _apply_chart_theme(figure, "Weekly Mileage")
    return figure


def running_progress_chart(activities_df: pd.DataFrame) -> go.Figure:
    runs = _running_activities(activities_df)
    if runs.empty:
        return _empty_figure("Running Progress", "No running activities available yet.")

    weekly = (
        runs.set_index("date")
        .resample("W-MON")
        .agg(distance=("distance", "sum"), duration=("duration", "sum"), activities=("id", "count"))
        .reset_index()
        .rename(columns={"date": "period"})
    )
    monthly = (
        runs.set_index("date")
        .resample("ME")
        .agg(distance=("distance", "sum"), duration=("duration", "sum"), activities=("id", "count"))
        .reset_index()
        .rename(columns={"date": "period"})
    )

    figure = go.Figure()
    figure.add_trace(
        go.Bar(
            x=weekly["period"],
            y=weekly["distance"],
            name="Weekly km",
            marker_color=STRAVA_ORANGE,
            customdata=weekly[["duration", "activities"]],
            hovertemplate=(
                "Week=%{x|%b %d}<br>Distance=%{y:.1f} km<br>"
                "Time=%{customdata[0]:.0f} min<br>Runs=%{customdata[1]}<extra></extra>"
            ),
        )
    )
    figure.add_trace(
        go.Scatter(
            x=monthly["period"],
            y=monthly["distance"],
            name="Monthly km",
            mode="lines+markers",
            line=dict(color=DEEP_INK, width=3),
            marker=dict(size=9, color=AMBER, line=dict(color=DEEP_INK, width=1)),
            customdata=monthly[["duration", "activities"]],
            hovertemplate=(
                "Month=%{x|%b %Y}<br>Distance=%{y:.1f} km<br>"
                "Time=%{customdata[0]:.0f} min<br>Runs=%{customdata[1]}<extra></extra>"
            ),
            yaxis="y2",
        )
    )
    _apply_chart_theme(figure, "Weekly and Monthly Running Progress")
    figure.update_layout(
        yaxis=dict(title="Weekly distance (km)"),
        yaxis2=dict(title="Monthly distance (km)", overlaying="y", side="right", showgrid=False),
    )
    return figure


def activity_calendar_chart(activities_df: pd.DataFrame) -> go.Figure:
    runs = _running_activities(activities_df)
    if runs.empty:
        return _empty_figure("Recent Running Log", "No running activities available yet.")

    recent = runs.tail(42).copy()
    recent["weekday"] = recent["date"].dt.day_name().str[:3]
    recent["pace_text"] = recent["pace"].apply(lambda value: f"{value:.2f} min/km" if pd.notna(value) else "n/a")
    size_values = recent["distance"].fillna(0).clip(lower=1) * 2.8

    figure = go.Figure(
        go.Scatter(
            x=recent["date"],
            y=recent["weekday"],
            mode="markers",
            marker=dict(
                size=size_values,
                color=recent["distance"].fillna(0),
                colorscale=[[0, "#fed7aa"], [1, STRAVA_ORANGE]],
                line=dict(color="white", width=2),
                showscale=True,
                colorbar=dict(title="km"),
            ),
            customdata=recent[["distance", "duration", "avg_hr", "pace_text", "type"]],
            hovertemplate=(
                "%{x|%Y-%m-%d}<br>%{customdata[4]}<br>"
                "Distance=%{customdata[0]:.1f} km<br>Duration=%{customdata[1]:.0f} min<br>"
                "Avg HR=%{customdata[2]:.0f} bpm<br>Pace=%{customdata[3]}<extra></extra>"
            ),
        )
    )
    _apply_chart_theme(figure, "Recent Running Log")
    figure.update_yaxes(categoryorder="array", categoryarray=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    figure.update_layout(height=360, showlegend=False)
    return figure


def pace_trend_chart(activities_df: pd.DataFrame) -> go.Figure:
    runs = activities_df.dropna(subset=["pace"]).copy()
    if runs.empty:
        return _empty_figure("Pace Trend")
    figure = px.line(
        runs,
        x="date",
        y="pace",
        color="type",
        title="Pace Trend",
        markers=True,
        color_discrete_sequence=[STRAVA_ORANGE, DEEP_INK, AMBER, GREEN],
    )
    figure.update_yaxes(autorange="reversed", title="min / km")
    _apply_chart_theme(figure, "Pace Trend")
    return figure


def hr_trend_chart(activities_df: pd.DataFrame) -> go.Figure:
    runs = activities_df.dropna(subset=["avg_hr"]).copy()
    if runs.empty:
        return _empty_figure("Average HR Trend")
    figure = px.line(
        runs,
        x="date",
        y="avg_hr",
        color="type",
        title="Average HR Trend",
        markers=True,
        color_discrete_sequence=[STRAVA_ORANGE, DEEP_INK, AMBER, GREEN],
    )
    _apply_chart_theme(figure, "Average HR Trend")
    figure.update_layout(yaxis_title="bpm")
    return figure


def vo2max_trend_chart(health_df: pd.DataFrame) -> go.Figure:
    df = health_df.dropna(subset=["vo2max"]).copy()
    if df.empty:
        return _empty_figure("VO2max Trend")
    figure = px.line(df, x="date", y="vo2max", title="VO2max Trend", markers=True, color_discrete_sequence=[STRAVA_ORANGE])
    _apply_chart_theme(figure, "VO2max Trend")
    return figure


def prediction_snapshot_chart(predictions_df: pd.DataFrame) -> go.Figure:
    if predictions_df.empty:
        return _empty_figure("Prediction Trend", "No prediction snapshots stored yet.")
    df = predictions_df.copy()
    df["prediction_date"] = pd.to_datetime(df["prediction_date"])
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=df["prediction_date"],
            y=df["predicted_time_minutes"],
            mode="lines+markers",
            name="Predicted finish",
            line=dict(color=STRAVA_ORANGE, width=3),
            marker=dict(size=9, color=STRAVA_ORANGE),
            customdata=df[["predicted_pace", "gap_minutes", "confidence", "activity_name"]],
            hovertemplate=(
                "%{x|%Y-%m-%d}<br>"
                "Predicted=%{y:.1f} min<br>"
                "Pace=%{customdata[0]:.2f} min/km<br>"
                "Gap=%{customdata[1]:+.1f} min<br>"
                "Confidence=%{customdata[2]:.0f}%<br>"
                "%{customdata[3]}<extra></extra>"
            ),
        )
    )
    figure.update_yaxes(title="Predicted finish (min)")
    return _apply_chart_theme(figure, "Prediction Trend")


def vo2max_activity_chart(health_df: pd.DataFrame, activities_df: pd.DataFrame) -> go.Figure:
    health = health_df.dropna(subset=["date"]).copy()
    activities = activities_df.dropna(subset=["date"]).copy()
    if health.empty or activities.empty:
        return _empty_figure("VO2max, HRV vs Same-Day Running")

    activities = activities[
        activities["type"].fillna("").str.contains("run", case=False, na=False)
    ].copy()
    if activities.empty:
        return _empty_figure("VO2max, HRV vs Same-Day Running", "No running activities available yet.")

    activities["type"] = activities["type"].fillna("activity")
    activities["distance"] = activities["distance"].fillna(0.0)
    activities["activity_label"] = activities.apply(
        lambda row: f"{row['type']} ({float(row['distance']):.1f} km)",
        axis=1,
    )
    activity_summary = (
        activities.groupby("date")
        .agg(
            total_distance=("distance", "sum"),
            total_duration=("duration", "sum"),
            activity_count=("id", "count"),
            average_hr=("avg_hr", "mean"),
        )
        .reset_index()
    )
    labels = (
        activities.groupby("date")["activity_label"]
        .apply(
            lambda items: ", ".join(items.iloc[:3]) + (" ..." if len(items) > 3 else "")
        )
        .reset_index(name="activity_summary")
    )
    mapped = (
        health[["date", "vo2max", "hrv"]]
        .merge(activity_summary, on="date", how="inner")
        .merge(labels, on="date", how="left")
    )
    mapped = mapped.dropna(subset=["vo2max", "hrv"], how="all")
    if mapped.empty:
        return _empty_figure(
            "VO2max, HRV vs Same-Day Running",
            "No days contain running activities with VO2max or HRV data.",
        )
    mapped["average_hr_text"] = mapped["average_hr"].apply(
        lambda value: f"{value:.0f} bpm" if pd.notna(value) else "n/a"
    )

    figure = go.Figure()
    figure.add_trace(
        go.Bar(
            x=mapped["date"],
            y=mapped["total_distance"],
            name="Activity Distance",
            marker_color=STRAVA_ORANGE,
            customdata=mapped[["activity_count", "total_duration", "average_hr_text", "activity_summary"]],
            hovertemplate=(
                "Date=%{x|%Y-%m-%d}<br>"
                "Distance=%{y:.1f} km<br>"
                "Activities=%{customdata[0]}<br>"
                "Duration=%{customdata[1]:.1f} min<br>"
                "Avg HR=%{customdata[2]}<br>"
                "Summary=%{customdata[3]}<extra></extra>"
            ),
        )
    )
    if mapped["vo2max"].notna().any():
        figure.add_trace(
            go.Scatter(
                x=mapped["date"],
                y=mapped["vo2max"],
                mode="lines+markers",
                name="VO2max",
                yaxis="y2",
                marker_color=DEEP_INK,
                hovertemplate="Date=%{x|%Y-%m-%d}<br>VO2max=%{y:.1f}<extra></extra>",
            )
        )
    if mapped["hrv"].notna().any():
        figure.add_trace(
            go.Scatter(
                x=mapped["date"],
                y=mapped["hrv"],
                mode="lines+markers",
                name="HRV",
                yaxis="y3",
                marker_color=GREEN,
                hovertemplate="Date=%{x|%Y-%m-%d}<br>HRV=%{y:.1f}<extra></extra>",
            )
        )
    _apply_chart_theme(figure, "VO2max, HRV vs Same-Day Running")
    figure.update_layout(
        barmode="group",
        yaxis=dict(title="Distance (km)"),
        yaxis2=dict(title="VO2max", overlaying="y", side="right"),
        yaxis3=dict(title="HRV", overlaying="y", side="right", anchor="free", position=0.94),
    )
    return figure


def sleep_recovery_chart(health_df: pd.DataFrame) -> go.Figure:
    if health_df.empty:
        return _empty_figure("Sleep and Recovery")
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(x=health_df["date"], y=health_df["sleep_score"], mode="lines+markers", name="Sleep Score", line=dict(color=GREEN, width=3))
    )
    figure.add_trace(
        go.Scatter(x=health_df["date"], y=health_df["recovery_time"], mode="lines+markers", name="Recovery Time (h)", yaxis="y2", line=dict(color=STRAVA_ORANGE, width=3))
    )
    _apply_chart_theme(figure, "Sleep and Recovery Trend")
    figure.update_layout(
        yaxis=dict(title="Sleep Score"),
        yaxis2=dict(title="Recovery Time (h)", overlaying="y", side="right"),
    )
    return figure


def hr_vs_pace_scatter(efficiency_df: pd.DataFrame) -> go.Figure:
    if efficiency_df.empty:
        return _empty_figure("HR vs Pace Efficiency")
    figure = px.scatter(
        efficiency_df,
        x="avg_hr",
        y="pace",
        size="distance",
        color="efficiency",
        hover_data=["date", "type"],
        title="HR vs Pace Efficiency",
    )
    figure.update_yaxes(autorange="reversed", title="min / km")
    _apply_chart_theme(figure, "HR vs Pace Efficiency")
    return figure


def long_run_progression_chart(long_run_df: pd.DataFrame) -> go.Figure:
    if long_run_df.empty:
        return _empty_figure("Long Run Progression")
    figure = px.line(long_run_df, x="week", y="distance", title="Long Run Progression", markers=True, color_discrete_sequence=[STRAVA_ORANGE])
    _apply_chart_theme(figure, "Long Run Progression")
    figure.update_layout(yaxis_title="km")
    return figure


def training_load_chart(load_df: pd.DataFrame) -> go.Figure:
    if load_df.empty:
        return _empty_figure("Training Load")
    figure = px.bar(load_df, x="date", y="training_load", title="Training Load Trend", color_discrete_sequence=[STRAVA_ORANGE])
    _apply_chart_theme(figure, "Training Load Trend")
    return figure


def intensity_distribution_chart(distribution: dict[str, float]) -> go.Figure:
    if not any(distribution.values()):
        return _empty_figure("Intensity Distribution")
    figure = px.pie(
        names=list(distribution.keys()),
        values=list(distribution.values()),
        title="Intensity Distribution",
        hole=0.4,
    )
    figure.update_traces(marker=dict(colors=[GREEN, AMBER, STRAVA_ORANGE]))
    _apply_chart_theme(figure, "Intensity Distribution")
    return figure


def sleep_performance_chart(correlation_df: pd.DataFrame) -> go.Figure:
    if correlation_df.empty:
        return _empty_figure("Sleep vs Performance")
    figure = px.scatter(
        correlation_df,
        x="sleep_score",
        y="pace",
        size="distance",
        color="avg_hr",
        hover_data=["date"],
        title="Sleep vs Running Pace",
    )
    figure.update_yaxes(autorange="reversed", title="min / km")
    _apply_chart_theme(figure, "Sleep vs Running Pace")
    return figure


def goal_pace_chart(activities_df: pd.DataFrame, goal_pace: float) -> go.Figure:
    runs = activities_df[
        activities_df["type"].fillna("").str.contains("run", case=False, na=False)
    ].dropna(subset=["pace"]).copy()
    if runs.empty:
        return _empty_figure("Goal Pace vs Actual")
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=runs["date"],
            y=runs["pace"],
            mode="lines+markers",
            name="Actual Pace",
            line=dict(color=STRAVA_ORANGE, width=3),
        )
    )
    figure.add_trace(
        go.Scatter(
            x=runs["date"],
            y=[goal_pace] * len(runs),
            mode="lines",
            name="Goal Pace",
            line=dict(dash="dash", color=DEEP_INK, width=2),
        )
    )
    _apply_chart_theme(figure, "Goal Pace vs Actual")
    figure.update_yaxes(autorange="reversed", title="min / km")
    return figure
