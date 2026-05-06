"""Runalyze-inspired training analysis page."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from ui.charts import hr_vs_pace_scatter, intensity_distribution_chart
from ui.components import apply_dashboard_theme
from utils.bootstrap import load_training_bundle
from utils.formatting import format_metric_number, format_pace

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


def _training_condition_frame(load: pd.DataFrame) -> pd.DataFrame:
    if load.empty:
        return pd.DataFrame(columns=["date", "daily_load", "acute_load", "chronic_load", "load_balance"])
    daily = load.copy()
    daily["date"] = pd.to_datetime(daily["date"])
    daily = (
        daily.set_index("date")["training_load"]
        .resample("D")
        .sum()
        .reset_index(name="daily_load")
    )
    daily["acute_load"] = daily["daily_load"].ewm(span=7, adjust=False).mean()
    daily["chronic_load"] = daily["daily_load"].ewm(span=42, adjust=False).mean()
    daily["load_balance"] = daily["acute_load"] - daily["chronic_load"]
    daily["load_ratio"] = daily["acute_load"] / daily["chronic_load"].replace(0, pd.NA)
    return daily


def _training_condition_chart(condition: pd.DataFrame) -> go.Figure:
    if condition.empty:
        return _themed_figure(go.Figure(), "Training Condition")
    figure = go.Figure()
    figure.add_trace(
        go.Bar(
            x=condition["date"],
            y=condition["daily_load"],
            name="Daily load",
            marker_color="rgba(252, 76, 2, 0.34)",
            hovertemplate="%{x|%Y-%m-%d}<br>Daily load=%{y:.0f}<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=condition["date"],
            y=condition["acute_load"],
            mode="lines",
            name="Acute load (7d)",
            line=dict(color=ANALYSIS_ORANGE, width=3),
            hovertemplate="%{x|%Y-%m-%d}<br>Acute load=%{y:.0f}<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=condition["date"],
            y=condition["chronic_load"],
            mode="lines",
            name="Chronic load (42d)",
            line=dict(color=ANALYSIS_BLUE, width=3),
            hovertemplate="%{x|%Y-%m-%d}<br>Chronic load=%{y:.0f}<extra></extra>",
        )
    )
    return _themed_figure(figure, "Training Condition: Acute vs Chronic Load")


def _strain_frame(load: pd.DataFrame) -> pd.DataFrame:
    if load.empty:
        return pd.DataFrame(columns=["week", "weekly_load", "monotony", "strain"])
    daily = load.copy()
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.set_index("date")["training_load"].resample("D").sum().reset_index(name="daily_load")
    daily["week"] = daily["date"].dt.to_period("W-MON").apply(lambda period: period.start_time)
    grouped = daily.groupby("week")["daily_load"]
    strain = grouped.agg(weekly_load="sum", mean_load="mean", load_std="std").reset_index()
    strain["monotony"] = strain["mean_load"] / strain["load_std"].replace(0, pd.NA)
    strain["monotony"] = strain["monotony"].fillna(0).clip(upper=6)
    strain["strain"] = strain["weekly_load"] * strain["monotony"]
    return strain


def _strain_chart(strain: pd.DataFrame) -> go.Figure:
    if strain.empty:
        return _themed_figure(go.Figure(), "Training Strain")
    figure = go.Figure()
    figure.add_trace(
        go.Bar(
            x=strain["week"],
            y=strain["strain"],
            name="Training strain",
            marker_color=ANALYSIS_AMBER,
            hovertemplate="Week=%{x|%b %d}<br>Strain=%{y:.0f}<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=strain["week"],
            y=strain["monotony"],
            name="Monotony",
            yaxis="y2",
            mode="lines+markers",
            line=dict(color=ANALYSIS_INK, width=3),
            hovertemplate="Week=%{x|%b %d}<br>Monotony=%{y:.2f}<extra></extra>",
        )
    )
    _themed_figure(figure, "Weekly Strain and Monotony")
    figure.update_layout(
        yaxis=dict(title="Strain"),
        yaxis2=dict(title="Monotony", overlaying="y", side="right", showgrid=False),
    )
    return figure


def _distance_histogram(runs: pd.DataFrame) -> go.Figure:
    if runs.empty:
        return _themed_figure(go.Figure(), "Distance Distribution")
    figure = px.histogram(
        runs,
        x="distance",
        nbins=14,
        color_discrete_sequence=[ANALYSIS_ORANGE],
        labels={"distance": "Distance (km)", "count": "Runs"},
    )
    figure.update_traces(marker_line_width=0, opacity=0.86)
    return _themed_figure(figure, "Distance Distribution")


def _monthly_pace_boxplot(runs: pd.DataFrame) -> go.Figure:
    pace_runs = runs.dropna(subset=["pace"]).copy()
    if pace_runs.empty:
        return _themed_figure(go.Figure(), "Monthly Pace Spread")
    pace_runs["month"] = pace_runs["date"].dt.strftime("%Y-%m")
    figure = px.box(
        pace_runs,
        x="month",
        y="pace",
        points="all",
        color_discrete_sequence=[ANALYSIS_BLUE],
        labels={"month": "Month", "pace": "Pace (min/km)"},
    )
    figure.update_yaxes(autorange="reversed")
    return _themed_figure(figure, "Monthly Pace Spread")


def _pace_curve_frame(runs: pd.DataFrame) -> pd.DataFrame:
    pace_runs = runs.dropna(subset=["distance", "pace"]).copy()
    buckets = [5.0, 10.0, 15.0, 21.1, 30.0, 42.2]
    rows = []
    for distance in buckets:
        eligible = pace_runs[pace_runs["distance"] >= distance]
        if eligible.empty:
            continue
        best = eligible.nsmallest(1, "pace").iloc[0]
        rows.append(
            {
                "distance": distance,
                "best_pace": float(best["pace"]),
                "source_date": best["date"],
                "source_distance": float(best["distance"]),
                "projected_time": float(best["pace"]) * distance,
            }
        )
    return pd.DataFrame(rows)


def _pace_curve_chart(curve: pd.DataFrame) -> go.Figure:
    if curve.empty:
        return _themed_figure(go.Figure(), "Pace Curve")
    figure = go.Figure(
        go.Scatter(
            x=curve["distance"],
            y=curve["best_pace"],
            mode="lines+markers",
            line=dict(color=ANALYSIS_ORANGE, width=4),
            marker=dict(size=11, color=ANALYSIS_ORANGE, line=dict(color="white", width=2)),
            customdata=curve[["source_date", "source_distance", "projected_time"]],
            hovertemplate=(
                "Distance=%{x:.1f} km<br>Best pace=%{y:.2f} min/km<br>"
                "Source=%{customdata[0]|%Y-%m-%d}, %{customdata[1]:.1f} km<br>"
                "Projected time=%{customdata[2]:.1f} min<extra></extra>"
            ),
        )
    )
    figure.update_yaxes(autorange="reversed", title="Best observed pace (min/km)")
    figure.update_xaxes(title="Distance bucket (km)")
    return _themed_figure(figure, "Performance Curve: Best Pace by Distance")


def _quality_sessions_frame(runs: pd.DataFrame) -> pd.DataFrame:
    if runs.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "type",
                "distance",
                "duration",
                "pace",
                "avg_hr",
                "aerobic_effect",
                "anaerobic_effect",
                "quality_type",
                "quality_score",
                "reason",
            ]
        )

    sessions = runs.copy()
    median_pace = sessions["pace"].dropna().median()
    long_run_threshold = max(16.0, sessions["distance"].quantile(0.80))
    tempo_pace_threshold = median_pace * 0.94 if pd.notna(median_pace) else None
    notes = sessions["notes"].fillna("").str.lower()
    session_type = sessions["type"].fillna("").str.lower()
    text = notes + " " + session_type

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
    if volume.empty:
        return _themed_figure(go.Figure(), "Quality Sessions")
    figure = go.Figure()
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
    if quality.empty:
        return _themed_figure(go.Figure(), "Quality Session Types")
    grouped = (
        quality.groupby("quality_type", as_index=False)
        .agg(distance=("distance", "sum"), sessions=("id", "count"))
        .sort_values("distance", ascending=True)
    )
    figure = go.Figure(
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


def _streak_frame(runs: pd.DataFrame) -> pd.DataFrame:
    if runs.empty:
        return pd.DataFrame(columns=["start", "end", "days", "distance"])
    daily = (
        runs.assign(day=runs["date"].dt.normalize())
        .groupby("day", as_index=False)
        .agg(distance=("distance", "sum"), activities=("id", "count"))
        .sort_values("day")
    )
    streaks = []
    current_start = None
    current_end = None
    current_distance = 0.0
    previous_day = None

    for row in daily.itertuples():
        day = pd.Timestamp(row.day)
        if previous_day is None or day == previous_day + pd.Timedelta(days=1):
            current_start = current_start or day
            current_end = day
            current_distance += float(row.distance or 0.0)
        else:
            streaks.append(
                {
                    "start": current_start,
                    "end": current_end,
                    "days": int((current_end - current_start).days + 1),
                    "distance": round(current_distance, 1),
                }
            )
            current_start = day
            current_end = day
            current_distance = float(row.distance or 0.0)
        previous_day = day

    if current_start is not None and current_end is not None:
        streaks.append(
            {
                "start": current_start,
                "end": current_end,
                "days": int((current_end - current_start).days + 1),
                "distance": round(current_distance, 1),
            }
        )
    return pd.DataFrame(streaks).sort_values(["days", "distance"], ascending=False)


def _calendar_heatmap_frame(runs: pd.DataFrame) -> pd.DataFrame:
    if runs.empty:
        return pd.DataFrame(columns=["date", "week", "weekday", "weekday_name", "distance", "activities"])
    daily = (
        runs.assign(date=runs["date"].dt.normalize())
        .groupby("date", as_index=False)
        .agg(distance=("distance", "sum"), activities=("id", "count"), duration=("duration", "sum"))
        .sort_values("date")
    )
    start = daily["date"].min()
    end = daily["date"].max()
    all_days = pd.DataFrame({"date": pd.date_range(start, end, freq="D")})
    heatmap = all_days.merge(daily, on="date", how="left").fillna(
        {"distance": 0.0, "activities": 0, "duration": 0.0}
    )
    heatmap["week"] = ((heatmap["date"] - heatmap["date"].min()).dt.days // 7).astype(int)
    heatmap["weekday"] = heatmap["date"].dt.weekday
    heatmap["weekday_name"] = heatmap["date"].dt.day_name().str[:3]
    return heatmap


def _streak_heatmap_chart(heatmap: pd.DataFrame) -> go.Figure:
    if heatmap.empty:
        return _themed_figure(go.Figure(), "Running Streak Heatmap")
    pivot = heatmap.pivot(index="weekday_name", columns="week", values="distance")
    weekday_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    pivot = pivot.reindex(weekday_order)
    hover = heatmap.pivot(index="weekday_name", columns="week", values="date").reindex(weekday_order)
    activities = heatmap.pivot(index="weekday_name", columns="week", values="activities").reindex(weekday_order)

    customdata = []
    for weekday in pivot.index:
        row = []
        for week in pivot.columns:
            date_value = hover.loc[weekday, week]
            activity_count = activities.loc[weekday, week]
            date_text = "" if pd.isna(date_value) else pd.Timestamp(date_value).strftime("%Y-%m-%d")
            activity_count = 0 if pd.isna(activity_count) else int(activity_count)
            row.append(
                [
                    date_text,
                    activity_count,
                ]
            )
        customdata.append(row)

    figure = go.Figure(
        go.Heatmap(
            z=pivot.to_numpy(),
            x=pivot.columns,
            y=pivot.index,
            customdata=customdata,
            colorscale=[
                [0.00, "#f1f5f9"],
                [0.15, "#fed7aa"],
                [0.45, "#fdba74"],
                [0.75, ANALYSIS_ORANGE],
                [1.00, "#7c2d12"],
            ],
            colorbar=dict(title="km"),
            xgap=3,
            ygap=3,
            hovertemplate=(
                "%{customdata[0]}<br>"
                "Distance=%{z:.1f} km<br>"
                "Activities=%{customdata[1]}<extra></extra>"
            ),
        )
    )
    _themed_figure(figure, "Running Streak Calendar Heatmap")
    figure.update_layout(height=330, xaxis_title="Training week", yaxis_title="")
    figure.update_yaxes(autorange="reversed")
    return figure


def _analysis_card(label: str, value: str, detail: str) -> None:
    st.markdown(
        f"""
        <div class="coach-card">
            <span class="coach-pill">{label}</span>
            <div class="coach-focus">{value}</div>
            <div class="coach-muted">{detail}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


apply_dashboard_theme()
st.title("Analysis")
st.caption(
    "Runalyze-inspired training analysis: load balance, performance curves, distributions, and efficiency signals."
)

bundle = load_training_bundle()
runs = _running_activities(bundle.activities)
snapshot = bundle.snapshot
condition = _training_condition_frame(snapshot["training_load"])
strain = _strain_frame(snapshot["training_load"])
pace_curve = _pace_curve_frame(runs)
quality_sessions = _quality_sessions_frame(runs)
quality_volume = _quality_volume_frame(runs, quality_sessions)
streaks = _streak_frame(runs)
heatmap = _calendar_heatmap_frame(runs)

if runs.empty:
    st.info("No running activities available yet. Import activities from the dashboard sidebar to unlock analysis.")
    st.stop()

latest_condition = condition.iloc[-1] if not condition.empty else None
latest_ratio = latest_condition.get("load_ratio") if latest_condition is not None else None
latest_ratio_text = format_metric_number(latest_ratio, decimals=2) if pd.notna(latest_ratio) else "n/a"
best_curve = pace_curve.nsmallest(1, "best_pace").iloc[0] if not pace_curve.empty else None
best_pace_text = format_pace(float(best_curve["best_pace"])) if best_curve is not None else "n/a"
longest_streak = streaks.iloc[0] if not streaks.empty else None
longest_streak_text = f"{int(longest_streak['days'])} days" if longest_streak is not None else "n/a"
quality_distance = float(quality_sessions["distance"].sum()) if not quality_sessions.empty else 0.0

c1, c2, c3, c4 = st.columns(4)
with c1:
    _analysis_card(
        "Effective VO2max",
        format_metric_number(snapshot["vo2max"].get("latest"), decimals=1),
        f"Trend: {snapshot['vo2max'].get('trend', 'n/a')}",
    )
with c2:
    _analysis_card(
        "Load ratio",
        latest_ratio_text,
        "Acute 7-day load compared with chronic 42-day load.",
    )
with c3:
    _analysis_card(
        "Best curve pace",
        best_pace_text,
        "Fastest observed pace among available distance buckets.",
    )
with c4:
    _analysis_card(
        "Longest streak",
        longest_streak_text,
        "Consecutive days with at least one running activity.",
    )

st.subheader("Quality Sessions")
st.caption(
    "Runalyze-style tempo-session review. Without lap splits, sessions are classified from pace, distance, effects, type, and notes."
)
q1, q2, q3, q4 = st.columns(4)
q1.metric("Quality sessions", len(quality_sessions))
q2.metric("Quality distance", f"{quality_distance:.1f} km")
q3.metric("Quality share", f"{quality_distance / max(float(runs['distance'].sum()), 1):.0%}")
latest_quality = quality_sessions["date"].max().strftime("%Y-%m-%d") if not quality_sessions.empty else "n/a"
q4.metric("Latest quality", latest_quality)

quality_col, type_col = st.columns([1.35, 1])
quality_col.plotly_chart(_quality_sessions_chart(quality_volume), width="stretch")
type_col.plotly_chart(_quality_type_chart(quality_sessions), width="stretch")
if quality_sessions.empty:
    st.info("No quality sessions detected yet. Add workout notes like tempo, threshold, interval, fartlek, or race to improve classification.")
else:
    table = quality_sessions.tail(20).sort_values("date", ascending=False).copy()
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

st.subheader("Training Load")
load_col, strain_col = st.columns(2)
load_col.plotly_chart(_training_condition_chart(condition), width="stretch")
strain_col.plotly_chart(_strain_chart(strain), width="stretch")

st.subheader("Performance Curves")
curve_col, efficiency_col = st.columns(2)
curve_col.plotly_chart(_pace_curve_chart(pace_curve), width="stretch")
efficiency_col.plotly_chart(hr_vs_pace_scatter(snapshot["efficiency"]["series"]), width="stretch")

st.subheader("Visual Statistics")
dist_col, pace_col = st.columns(2)
dist_col.plotly_chart(_distance_histogram(runs), width="stretch")
pace_col.plotly_chart(_monthly_pace_boxplot(runs), width="stretch")

st.subheader("Running Streaks")
st.caption("Consecutive training days can be motivating, but keep recovery quality higher than the streak.")
st.plotly_chart(_streak_heatmap_chart(heatmap), width="stretch")
if not streaks.empty:
    streak_table = streaks.head(8).copy()
    streak_table["start"] = streak_table["start"].dt.date
    streak_table["end"] = streak_table["end"].dt.date
    st.dataframe(streak_table[["start", "end", "days", "distance"]], width="stretch")

st.subheader("Intensity and Latest Activities")
intensity_col, table_col = st.columns([0.8, 1.2])
intensity_col.plotly_chart(intensity_distribution_chart(snapshot["intensity"]["distribution"]), width="stretch")
table_col.dataframe(
    runs.tail(12)[["date", "type", "distance", "duration", "pace", "avg_hr", "aerobic_effect", "anaerobic_effect"]]
    .sort_values("date", ascending=False),
    width="stretch",
)
