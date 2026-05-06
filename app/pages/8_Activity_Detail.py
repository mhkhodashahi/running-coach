"""Activity detail page."""

from __future__ import annotations

from html import escape

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from config import get_settings
from db import repository
from db.session import session_scope
from ui.components import apply_dashboard_theme
from ui.google_maps import render_activity_route_map
from utils.bootstrap import load_training_bundle
from utils.formatting import format_duration_minutes, format_metric_number, format_pace

DETAIL_ORANGE = "#fc4c02"
DETAIL_INK = "#111827"
DETAIL_MUTED = "#64748b"
DETAIL_BLUE = "#2563eb"
DETAIL_GREEN = "#16a34a"
DETAIL_AMBER = "#f59e0b"


def _running_activities(activities: pd.DataFrame) -> pd.DataFrame:
    if activities.empty:
        return activities.copy()
    runs = activities[
        activities["type"].fillna("").str.contains("run|trail|treadmill", case=False, na=False)
    ].copy()
    if not runs.empty:
        runs["date"] = pd.to_datetime(runs["date"])
        runs = runs.sort_values("date")
    return runs


def _themed_figure(figure: go.Figure, title: str) -> go.Figure:
    figure.update_layout(
        title=title,
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.52)",
        font=dict(family="Manrope, sans-serif", color=DETAIL_INK),
        title_font=dict(size=20),
        margin=dict(l=34, r=28, t=58, b=38),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    figure.update_xaxes(gridcolor="rgba(100,116,139,0.16)", zeroline=False)
    figure.update_yaxes(gridcolor="rgba(100,116,139,0.16)", zeroline=False)
    return figure


def _activity_title(activity: pd.Series) -> str:
    activity_type = str(activity.get("type") or "Activity").replace("_", " ").title()
    date_text = pd.Timestamp(activity["date"]).strftime("%A, %d %B %Y")
    return f"{activity_type} on {date_text}"


def _relative_effort(activity: pd.Series, user_max_hr: int | None) -> float:
    duration = float(activity.get("duration") or 0.0)
    avg_hr = float(activity.get("avg_hr") or 0.0)
    aerobic = float(activity.get("aerobic_effect") or 0.0)
    anaerobic = float(activity.get("anaerobic_effect") or 0.0)
    if user_max_hr and avg_hr:
        hr_ratio = avg_hr / user_max_hr
        return round(duration * max(hr_ratio - 0.55, 0.05) * 1.7 + aerobic * 8 + anaerobic * 12, 1)
    return round(duration * 0.18 + aerobic * 8 + anaerobic * 12, 1)


def _effort_label(effort: float) -> str:
    if effort >= 95:
        return "Very hard"
    if effort >= 65:
        return "Hard"
    if effort >= 35:
        return "Moderate"
    return "Easy"


def _context_delta(value: float | None, baseline: float | None, *, lower_is_better: bool = False) -> str:
    if value is None or baseline is None or pd.isna(value) or pd.isna(baseline):
        return "n/a"
    delta = float(value) - float(baseline)
    if lower_is_better:
        label = "faster" if delta < 0 else "slower"
        return f"{abs(delta):.2f} min/km {label} than recent median"
    label = "above" if delta >= 0 else "below"
    return f"{abs(delta):.1f} {label} recent median"


def _render_activity_hero(activity: pd.Series, effort: float) -> None:
    title = escape(_activity_title(activity))
    distance = float(activity.get("distance") or 0.0)
    duration = float(activity.get("duration") or 0.0)
    pace = activity.get("pace")
    effort_text = escape(_effort_label(effort))
    notes = escape(str(activity.get("notes") or "No notes added yet."))
    st.markdown(
        f"""
        <section class="activity-hero">
            <div class="activity-copy">
                <span class="coach-pill">Activity detail</span>
                <h1>{title}</h1>
                <p>{notes}</p>
            </div>
            <div class="activity-stat-row">
                <div><strong>{distance:.2f}</strong><span>km</span></div>
                <div><strong>{format_duration_minutes(duration)}</strong><span>elapsed time</span></div>
                <div><strong>{format_pace(float(pace)) if pd.notna(pace) else "n/a"}</strong><span>avg pace</span></div>
                <div><strong>{effort_text}</strong><span>relative effort</span></div>
            </div>
        </section>
        <style>
            .activity-hero {{
                position: relative;
                overflow: hidden;
                border-radius: 30px;
                padding: 30px;
                margin-bottom: 22px;
                color: white;
                background:
                    radial-gradient(circle at 88% 12%, rgba(252, 76, 2, 0.86), transparent 30%),
                    linear-gradient(135deg, #111827 0%, #1f2937 100%);
                box-shadow: 0 26px 70px rgba(15, 23, 42, 0.22);
            }}
            .activity-copy h1 {{
                max-width: 850px;
                margin: 14px 0 8px;
                color: white;
                font-size: clamp(2rem, 4vw, 4rem);
                line-height: 0.95;
                letter-spacing: -0.05em;
            }}
            .activity-copy p {{
                max-width: 760px;
                color: #cbd5e1;
                margin: 0;
            }}
            .activity-stat-row {{
                display: grid;
                grid-template-columns: repeat(4, minmax(130px, 1fr));
                gap: 12px;
                margin-top: 26px;
            }}
            .activity-stat-row div {{
                background: rgba(255, 255, 255, 0.10);
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-radius: 20px;
                padding: 16px;
                backdrop-filter: blur(10px);
            }}
            .activity-stat-row strong {{
                display: block;
                color: white;
                font-size: 1.45rem;
                letter-spacing: -0.04em;
            }}
            .activity-stat-row span {{
                color: #cbd5e1;
                font-size: 0.78rem;
                text-transform: uppercase;
                letter-spacing: 0.06em;
                font-weight: 800;
            }}
            .activity-map-card {{
                min-height: 360px;
                border-radius: 26px;
                border: 1px solid rgba(15, 23, 42, 0.10);
                background:
                    linear-gradient(135deg, rgba(252, 76, 2, 0.16), transparent 36%),
                    repeating-linear-gradient(0deg, rgba(15, 23, 42, 0.05) 0 1px, transparent 1px 32px),
                    repeating-linear-gradient(90deg, rgba(15, 23, 42, 0.05) 0 1px, transparent 1px 32px),
                    #f8fafc;
                box-shadow: 0 18px 45px rgba(15, 23, 42, 0.08);
                padding: 24px;
                display: flex;
                flex-direction: column;
                justify-content: space-between;
            }}
            .activity-map-card h3 {{
                margin: 0;
                font-size: 1.3rem;
            }}
            .activity-map-line {{
                height: 150px;
                border-radius: 999px;
                border: 11px solid {DETAIL_ORANGE};
                border-left-color: transparent;
                border-bottom-color: {DETAIL_BLUE};
                transform: rotate(-13deg);
                opacity: 0.88;
                margin: 26px auto;
                width: min(72%, 420px);
            }}
            @media (max-width: 760px) {{
                .activity-stat-row {{
                    grid-template-columns: 1fr 1fr;
                }}
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _activity_context_chart(runs: pd.DataFrame, activity: pd.Series) -> go.Figure:
    figure = go.Figure()
    comparable = runs.dropna(subset=["distance", "pace"]).copy()
    if comparable.empty:
        return _themed_figure(figure, "Activity Context")
    figure.add_trace(
        go.Scatter(
            x=comparable["distance"],
            y=comparable["pace"],
            mode="markers",
            name="Other runs",
            marker=dict(size=9, color="rgba(100, 116, 139, 0.38)", line=dict(width=0)),
            hovertemplate="%{x:.1f} km<br>%{y:.2f} min/km<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=[activity["distance"]],
            y=[activity["pace"]],
            mode="markers",
            name="Selected activity",
            marker=dict(size=18, color=DETAIL_ORANGE, line=dict(color="white", width=3)),
            hovertemplate="Selected<br>%{x:.1f} km<br>%{y:.2f} min/km<extra></extra>",
        )
    )
    figure.update_yaxes(autorange="reversed", title="Pace (min/km)")
    figure.update_xaxes(title="Distance (km)")
    return _themed_figure(figure, "Pace vs Distance Context")


def _effort_breakdown_chart(activity: pd.Series, effort: float) -> go.Figure:
    values = {
        "Relative effort": effort,
        "Aerobic effect": float(activity.get("aerobic_effect") or 0.0) * 22,
        "Anaerobic effect": float(activity.get("anaerobic_effect") or 0.0) * 22,
        "Elevation": min(float(activity.get("elevation") or 0.0) / 2.5, 100),
    }
    figure = go.Figure(
        go.Bar(
            x=list(values.values()),
            y=list(values.keys()),
            orientation="h",
            marker_color=[DETAIL_ORANGE, DETAIL_GREEN, DETAIL_AMBER, DETAIL_BLUE],
            hovertemplate="%{y}: %{x:.1f}<extra></extra>",
        )
    )
    figure.update_xaxes(title="Scaled score", range=[0, max(100, max(values.values()) * 1.1)])
    return _themed_figure(figure, "Effort Breakdown")


def _route_chart(track_points: pd.DataFrame) -> go.Figure:
    route = track_points.dropna(subset=["latitude", "longitude"]).copy()
    figure = go.Figure()
    if route.empty:
        return _themed_figure(figure, "GPS Route")
    figure.add_trace(
        go.Scatter(
            x=route["longitude"],
            y=route["latitude"],
            mode="lines",
            name="Route",
            line=dict(color=DETAIL_ORANGE, width=5),
            hovertemplate="Lat=%{y:.5f}<br>Lon=%{x:.5f}<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=[route["longitude"].iloc[0], route["longitude"].iloc[-1]],
            y=[route["latitude"].iloc[0], route["latitude"].iloc[-1]],
            mode="markers",
            name="Start / finish",
            marker=dict(size=[12, 14], color=[DETAIL_GREEN, DETAIL_INK], line=dict(color="white", width=2)),
            hovertemplate="%{fullData.name}<br>Lat=%{y:.5f}<br>Lon=%{x:.5f}<extra></extra>",
        )
    )
    figure.update_xaxes(title="Longitude", scaleanchor="y", scaleratio=1)
    figure.update_yaxes(title="Latitude")
    return _themed_figure(figure, "GPS Route")


def _stream_x_axis(track_points: pd.DataFrame, activity_distance_km: float) -> tuple[pd.Series, str, list[float] | None]:
    elapsed = pd.to_numeric(track_points.get("elapsed_seconds"), errors="coerce")
    if elapsed.notna().any():
        elapsed_minutes = elapsed / 60
        return elapsed_minutes, "Elapsed time (min)", None

    distance = pd.to_numeric(track_points.get("distance_km"), errors="coerce")
    max_allowed_distance = float(activity_distance_km or 0.0) + 0.25
    if distance.notna().any() and max_allowed_distance > 0:
        cleaned = distance.ffill()
        is_monotonic = cleaned.dropna().is_monotonic_increasing
        ends_near_activity = cleaned.max() <= max_allowed_distance
        if is_monotonic and ends_near_activity:
            return cleaned, "Distance (km)", [0, max_allowed_distance]

    index_axis = pd.Series(range(len(track_points)), index=track_points.index)
    return index_axis, "Stream point", None


def _track_metrics_chart(track_points: pd.DataFrame, activity_distance_km: float) -> go.Figure:
    if track_points.empty:
        return _themed_figure(go.Figure(), "Activity Stream")

    x_axis, x_title, x_range = _stream_x_axis(track_points, activity_distance_km)
    pace = pd.to_numeric(track_points["pace"], errors="coerce")
    heart_rate = pd.to_numeric(track_points["heart_rate"], errors="coerce")

    figure = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.55, 0.45],
        subplot_titles=("Pace", "Heart Rate"),
    )
    if pace.notna().any():
        figure.add_trace(
            go.Scatter(
                x=x_axis,
                y=pace,
                mode="lines",
                name="Pace (min/km)",
                line=dict(color=DETAIL_ORANGE, width=3),
                hovertemplate=f"{x_title}=%{{x:.2f}}<br>Pace=%{{y:.2f}} min/km<extra></extra>",
            ),
            row=1,
            col=1,
        )
    if heart_rate.notna().any():
        figure.add_trace(
            go.Scatter(
                x=x_axis,
                y=heart_rate,
                mode="lines",
                name="Heart rate (bpm)",
                line=dict(color=DETAIL_BLUE, width=3),
                hovertemplate=f"{x_title}=%{{x:.2f}}<br>HR=%{{y:.0f}} bpm<extra></extra>",
            ),
            row=2,
            col=1,
        )

    _themed_figure(figure, "Activity Stream")
    figure.update_layout(
        height=520,
        showlegend=True,
    )
    figure.update_yaxes(title="min/km", autorange="reversed", row=1, col=1)
    figure.update_yaxes(title="bpm", row=2, col=1)
    figure.update_xaxes(title=x_title, row=2, col=1)
    if x_range is not None:
        figure.update_xaxes(range=x_range, row=1, col=1)
        figure.update_xaxes(range=x_range, row=2, col=1)
    return figure


def _laps_chart(laps: pd.DataFrame) -> go.Figure:
    figure = go.Figure()
    if laps.empty:
        return _themed_figure(figure, "Laps")
    chart_data = laps.copy()
    chart_data["lap_index"] = pd.to_numeric(chart_data["lap_index"], errors="coerce")
    chart_data["pace"] = pd.to_numeric(chart_data["pace"], errors="coerce")
    chart_data = chart_data.dropna(subset=["lap_index", "pace"]).sort_values("lap_index")
    if chart_data.empty:
        return _themed_figure(figure, "Lap Pace")
    figure.add_trace(
        go.Bar(
            x=chart_data["pace"],
            y=chart_data["lap_index"],
            name="Lap pace",
            orientation="h",
            marker_color=DETAIL_ORANGE,
            customdata=chart_data[["distance", "duration", "avg_hr"]],
            hovertemplate=(
                "Lap=%{y}<br>Pace=%{x:.2f} min/km<br>"
                "Distance=%{customdata[0]:.2f} km<br>Duration=%{customdata[1]:.2f} min<br>"
                "Avg HR=%{customdata[2]:.0f} bpm<extra></extra>"
            ),
        )
    )
    figure.update_xaxes(title="Pace (min/km)", rangemode="tozero")
    figure.update_yaxes(title="Lap", tickmode="linear", dtick=1, autorange="reversed")
    return _themed_figure(figure, "Lap Pace")


def _similar_activities(runs: pd.DataFrame, activity: pd.Series) -> pd.DataFrame:
    comparable = runs[runs["id"] != activity["id"]].dropna(subset=["distance"]).copy()
    if comparable.empty:
        return comparable
    target_distance = float(activity.get("distance") or 0.0)
    comparable["distance_gap"] = (comparable["distance"] - target_distance).abs()
    return comparable.nsmallest(6, "distance_gap")


def _load_activity_detail_data(activity_id: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load GPS points and laps, tolerating stale Streamlit module state during hot reload."""

    with session_scope() as session:
        if hasattr(repository, "track_points_dataframe") and hasattr(repository, "activity_laps_dataframe"):
            return (
                repository.track_points_dataframe(session, activity_id),
                repository.activity_laps_dataframe(session, activity_id),
            )

        track_points = pd.read_sql_query(
            """
            SELECT id, activity_id, point_index, timestamp, elapsed_seconds, distance_km,
                   latitude, longitude, elevation, pace, speed, heart_rate, cadence
            FROM activity_track_points
            WHERE activity_id = :activity_id
            ORDER BY point_index ASC
            """,
            session.bind,
            params={"activity_id": activity_id},
        )
        laps = pd.read_sql_query(
            """
            SELECT id, activity_id, lap_index, lap_type, start_time, duration, distance,
                   pace, avg_hr, max_hr, elevation_gain, avg_cadence
            FROM activity_laps
            WHERE activity_id = :activity_id
            ORDER BY lap_index ASC
            """,
            session.bind,
            params={"activity_id": activity_id},
        )
        if not track_points.empty:
            track_points["timestamp"] = pd.to_datetime(track_points["timestamp"])
        if not laps.empty:
            laps["start_time"] = pd.to_datetime(laps["start_time"])
        return track_points, laps


apply_dashboard_theme()
st.title("Activity Detail")
st.caption("Strava-inspired activity view using your locally stored Garmin-style activity data.")

settings = get_settings()
bundle = load_training_bundle()
activities = bundle.activities.copy()
if activities.empty:
    st.info("No activities available yet. Import a CSV or sync Garmin data from the dashboard sidebar.")
    st.stop()

activities["date"] = pd.to_datetime(activities["date"])
runs = _running_activities(activities)
options = {
    f"{row.id} | {row.date:%Y-%m-%d} | {row.type} | {row.distance:.2f} km": int(row.id)
    for row in activities.sort_values("date", ascending=False).itertuples()
}
selected_activity_id = st.session_state.get("selected_activity_id")
query_activity_id = st.query_params.get("activity_id")
if query_activity_id:
    try:
        selected_activity_id = int(query_activity_id)
    except (TypeError, ValueError):
        selected_activity_id = selected_activity_id

option_labels = list(options.keys())
selected_index = 0
if selected_activity_id in options.values():
    selected_index = list(options.values()).index(selected_activity_id)

selected_label = st.selectbox("Choose activity", option_labels, index=selected_index)
selected_id = options[selected_label]
st.session_state["selected_activity_id"] = int(selected_id)
activity = activities.loc[activities["id"] == selected_id].iloc[0]
track_points, laps = _load_activity_detail_data(int(selected_id))

recent_runs = runs.tail(30)
median_pace = recent_runs["pace"].dropna().median() if not recent_runs.empty else None
median_hr = recent_runs["avg_hr"].dropna().median() if not recent_runs.empty else None
effort = _relative_effort(activity, getattr(bundle.user, "max_hr", None))

_render_activity_hero(activity, effort)

stats = st.columns(4)
stats[0].metric("Average HR", format_metric_number(activity.get("avg_hr"), decimals=0, suffix=" bpm"), _context_delta(activity.get("avg_hr"), median_hr))
stats[1].metric("Max HR", format_metric_number(activity.get("max_hr"), decimals=0, suffix=" bpm"))
stats[2].metric("Cadence", format_metric_number(activity.get("cadence"), decimals=0, suffix=" spm"))
stats[3].metric("Elevation", format_metric_number(activity.get("elevation"), decimals=0, suffix=" m"))

main_col, side_col = st.columns([1.35, 1])
with main_col:
    if track_points[["latitude", "longitude"]].dropna().empty:
        st.markdown(
            f"""
            <div class="activity-map-card">
                <div>
                    <span class="coach-pill">Route preview</span>
                    <h3>GPS route stream is not stored yet</h3>
                    <p style="color:{DETAIL_MUTED}; max-width:640px;">
                        Sync this activity from Garmin with detail data to render the actual route here.
                    </p>
                </div>
                <div class="activity-map-line"></div>
                <p style="color:{DETAIL_MUTED}; margin:0;">Activity id: {int(activity['id'])}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        render_activity_route_map(
            track_points,
            api_key=settings.google_maps_api_key,
            map_id=settings.google_maps_map_id,
            muted_color=DETAIL_MUTED,
        )
with side_col:
    st.plotly_chart(_effort_breakdown_chart(activity, effort), width="stretch")

if not track_points.empty:
    st.plotly_chart(_track_metrics_chart(track_points, float(activity.get("distance") or 0.0)), width="stretch")

if not laps.empty:
    lap_chart_col, lap_table_col = st.columns([1.15, 1])
    lap_chart_col.plotly_chart(_laps_chart(laps), width="stretch")
    lap_table = laps.copy()
    if "start_time" in lap_table:
        lap_table["start_time"] = lap_table["start_time"].dt.strftime("%Y-%m-%d %H:%M:%S")
    lap_table_col.dataframe(
        lap_table[["lap_index", "lap_type", "distance", "duration", "pace", "avg_hr", "max_hr", "elevation_gain", "avg_cadence"]],
        width="stretch",
    )

chart_col, detail_col = st.columns(2)
with chart_col:
    if str(activity.get("type") or "").lower().find("run") >= 0 and pd.notna(activity.get("pace")):
        st.plotly_chart(_activity_context_chart(runs, activity), width="stretch")
    else:
        st.info("Pace context is available for running activities with pace data.")
with detail_col:
    st.subheader("Session Notes")
    st.write(activity.get("notes") or "No notes for this activity yet.")
    st.subheader("Pace Context")
    st.write(
        _context_delta(
            float(activity["pace"]) if pd.notna(activity.get("pace")) else None,
            float(median_pace) if pd.notna(median_pace) else None,
            lower_is_better=True,
        )
    )
    st.write(f"Relative effort estimate: **{effort:.1f}** ({_effort_label(effort)}).")

st.subheader("Similar Distance Activities")
similar = _similar_activities(runs if str(activity.get("type") or "").lower().find("run") >= 0 else activities, activity)
if similar.empty:
    st.caption("No similar activities available yet.")
else:
    similar_table = similar.copy()
    similar_table["date"] = similar_table["date"].dt.date
    st.dataframe(
        similar_table[["date", "type", "distance", "duration", "pace", "avg_hr", "aerobic_effect", "anaerobic_effect"]],
        width="stretch",
    )
