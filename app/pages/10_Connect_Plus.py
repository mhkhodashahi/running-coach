"""Garmin Connect+ inspired premium dashboard."""

from __future__ import annotations

from datetime import date
from html import escape

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import get_settings
from db import repository
from db.session import session_scope
from services.connect_plus import (
    build_active_intelligence_cards,
    build_training_guidance,
    daily_nutrition_summary,
    estimate_nutrition_targets,
    generate_active_intelligence,
    running_activities,
)
from ui.components import apply_dashboard_theme
from ui.google_maps import render_activity_route_map
from utils.bootstrap import load_training_bundle
from utils.formatting import format_duration_minutes, format_metric_number, format_pace

ORANGE = "#fc4c02"
INK = "#111827"
MUTED = "#64748b"
BLUE = "#2563eb"
GREEN = "#16a34a"
AMBER = "#f59e0b"


def _premium_hero() -> None:
    st.markdown(
        """
        <section class="connect-plus-hero">
            <span class="coach-pill">Connect+ Premium</span>
            <h1>Deeper coaching from the data you already own.</h1>
            <p>AI-style insights, custom performance analysis, training guidance, 3D route views, and nutrition tracking.</p>
        </section>
        <style>
            .connect-plus-hero {
                border-radius: 28px;
                padding: 30px;
                margin-bottom: 20px;
                color: white;
                background:
                    linear-gradient(135deg, rgba(17, 24, 39, 0.96), rgba(30, 41, 59, 0.92)),
                    linear-gradient(90deg, rgba(252, 76, 2, 0.34), transparent);
                box-shadow: 0 24px 64px rgba(15, 23, 42, 0.18);
            }
            .connect-plus-hero h1 {
                color: white;
                margin: 14px 0 8px;
                max-width: 860px;
                font-size: clamp(2rem, 4vw, 4.4rem);
                line-height: 0.96;
                letter-spacing: -0.05em;
            }
            .connect-plus-hero p {
                color: #cbd5e1;
                max-width: 760px;
                margin: 0;
            }
            .premium-card {
                height: 100%;
                border-radius: 20px;
                border: 1px solid rgba(15, 23, 42, 0.10);
                background: rgba(255, 255, 255, 0.82);
                box-shadow: 0 16px 40px rgba(15, 23, 42, 0.07);
                padding: 18px;
            }
            .premium-card h3 {
                margin: 8px 0 8px;
                letter-spacing: -0.03em;
            }
            .premium-status {
                display: inline-block;
                border-radius: 999px;
                padding: 5px 9px;
                color: #fff;
                background: #111827;
                font-size: 0.72rem;
                font-weight: 800;
                text-transform: uppercase;
                letter-spacing: 0.06em;
            }
            .premium-muted {
                color: #64748b;
                margin: 0;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _daily_performance_frame(
    activities: pd.DataFrame,
    health: pd.DataFrame,
    nutrition_entries: pd.DataFrame,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    if not activities.empty:
        act = activities.copy()
        act["date"] = pd.to_datetime(act["date"]).dt.normalize()
        frames.append(
            act.groupby("date")
            .agg(
                distance_km=("distance", "sum"),
                duration_min=("duration", "sum"),
                avg_hr=("avg_hr", "mean"),
                elevation_m=("elevation", "sum"),
                activity_count=("id", "count"),
            )
            .reset_index()
        )
    if not health.empty:
        h = health.copy()
        h["date"] = pd.to_datetime(h["date"]).dt.normalize()
        frames.append(
            h[
                [
                    "date",
                    "sleep_score",
                    "sleep_duration",
                    "resting_hr",
                    "hrv",
                    "stress",
                    "body_battery",
                    "recovery_time",
                    "vo2max",
                ]
            ]
        )
    nutrition = daily_nutrition_summary(nutrition_entries)
    if not nutrition.empty:
        nutrition = nutrition.rename(columns={"entry_date": "date"})
        nutrition["date"] = pd.to_datetime(nutrition["date"]).dt.normalize()
        frames.append(nutrition)
    if not frames:
        return pd.DataFrame(columns=["date"])
    merged = frames[0]
    for frame in frames[1:]:
        merged = merged.merge(frame, on="date", how="outer")
    return merged.sort_values("date")


def _filter_period(df: pd.DataFrame, days: int) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=days - 1)
    return df[pd.to_datetime(df["date"]) >= cutoff].copy()


def _custom_metric_chart(df: pd.DataFrame, metrics: list[str]) -> go.Figure:
    figure = go.Figure()
    if df.empty or not metrics:
        figure.add_annotation(text="No matching data yet.", x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False)
    else:
        for metric in metrics:
            if metric not in df.columns:
                continue
            values = pd.to_numeric(df[metric], errors="coerce")
            if values.notna().any():
                figure.add_trace(
                    go.Scatter(
                        x=df["date"],
                        y=values,
                        mode="lines+markers",
                        name=metric.replace("_", " ").title(),
                        hovertemplate="%{x|%Y-%m-%d}<br>%{y:.1f}<extra></extra>",
                    )
                )
    figure.update_layout(
        title="Custom Performance Graph",
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.45)",
        font=dict(color=INK),
        margin=dict(l=34, r=28, t=58, b=38),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return figure


def _correlation_chart(df: pd.DataFrame, metrics: list[str]) -> go.Figure:
    usable = df[[metric for metric in metrics if metric in df.columns]].apply(pd.to_numeric, errors="coerce")
    usable = usable.dropna(axis=1, how="all")
    if usable.shape[1] < 2:
        return go.Figure().add_annotation(
            text="At least two populated metrics are needed for correlation.",
            x=0.5,
            y=0.5,
            xref="paper",
            yref="paper",
            showarrow=False,
        )
    corr = usable.corr(numeric_only=True)
    figure = px.imshow(
        corr,
        text_auto=".2f",
        color_continuous_scale="RdBu",
        zmin=-1,
        zmax=1,
        title="Metric Correlation",
    )
    figure.update_layout(template="plotly_white", paper_bgcolor="rgba(0,0,0,0)", margin=dict(l=34, r=28, t=58, b=38))
    return figure


def _nutrition_chart(summary: pd.DataFrame) -> go.Figure:
    if summary.empty:
        figure = go.Figure()
        figure.add_annotation(text="Log nutrition to see calories and macros.", x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False)
        figure.update_layout(title="Nutrition Trend", template="plotly_white", paper_bgcolor="rgba(0,0,0,0)")
        return figure
    df = summary.copy()
    figure = go.Figure()
    figure.add_trace(go.Bar(x=df["entry_date"], y=df["calories"], name="Calories", marker_color=ORANGE))
    for metric, color in (("protein_g", GREEN), ("carbs_g", BLUE), ("fat_g", AMBER)):
        figure.add_trace(
            go.Scatter(
                x=df["entry_date"],
                y=df[metric],
                yaxis="y2",
                mode="lines+markers",
                name=metric.replace("_g", "").title(),
                line=dict(color=color, width=3),
            )
        )
    figure.update_layout(
        title="Calories and Macros",
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        yaxis=dict(title="Calories"),
        yaxis2=dict(title="Grams", overlaying="y", side="right"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=34, r=28, t=58, b=38),
    )
    return figure


def _route_3d_chart(track_points: pd.DataFrame, activity: pd.Series | None) -> go.Figure:
    route = track_points.dropna(subset=["latitude", "longitude"]).copy() if not track_points.empty else pd.DataFrame()
    figure = go.Figure()
    if not route.empty:
        elevation = pd.to_numeric(route.get("elevation"), errors="coerce").ffill().fillna(0)
        figure.add_trace(
            go.Scatter3d(
                x=route["longitude"],
                y=route["latitude"],
                z=elevation,
                mode="lines",
                line=dict(color=ORANGE, width=7),
                name="GPS route",
                hovertemplate="Lon=%{x:.5f}<br>Lat=%{y:.5f}<br>Elevation=%{z:.0f} m<extra></extra>",
            )
        )
        figure.add_trace(
            go.Scatter3d(
                x=[route["longitude"].iloc[0], route["longitude"].iloc[-1]],
                y=[route["latitude"].iloc[0], route["latitude"].iloc[-1]],
                z=[elevation.iloc[0], elevation.iloc[-1]],
                mode="markers",
                marker=dict(size=5, color=[GREEN, INK]),
                name="Start / finish",
            )
        )
    elif activity is not None:
        distance = max(float(activity.get("distance") or 1.0), 1.0)
        elevation_gain = max(float(activity.get("elevation") or 0.0), 20.0)
        x_values = [idx * distance / 80 for idx in range(81)]
        z_values = [
            elevation_gain * (0.35 + 0.35 * __import__("math").sin(idx / 8) + idx / 160)
            for idx in range(81)
        ]
        figure.add_trace(
            go.Scatter3d(
                x=x_values,
                y=[0.4 * __import__("math").sin(idx / 12) for idx in range(81)],
                z=z_values,
                mode="lines",
                line=dict(color=ORANGE, width=7),
                name="Elevation model",
                hovertemplate="Distance=%{x:.1f} km<br>Relative elevation=%{z:.0f} m<extra></extra>",
            )
        )
    else:
        figure.add_annotation(text="Select an activity to render a 3D route view.", x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False)
    figure.update_layout(
        title="3D Route View",
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=48, b=0),
        height=620,
        scene=dict(
            xaxis_title="Longitude / Distance",
            yaxis_title="Latitude / Drift",
            zaxis_title="Elevation",
            camera=dict(eye=dict(x=1.45, y=-1.55, z=1.0)),
        ),
    )
    return figure


def _load_track_points(activity_id: int) -> pd.DataFrame:
    with session_scope() as session:
        return repository.track_points_dataframe(session, activity_id)


def _render_active_intelligence(bundle, snapshot: dict, nutrition_entries: pd.DataFrame) -> None:
    st.caption(
        "Garmin-style Active Intelligence. Smart generation is opt-in and sends a summarized training context "
        "to the configured LLM provider."
    )
    consent = st.toggle(
        "Enable smart Active Intelligence",
        value=bool(st.session_state.get("active_intelligence_consent", False)),
        help="When enabled, clicking Generate sends summarized activity, health, goal, and nutrition context to the configured LLM provider.",
    )
    st.session_state["active_intelligence_consent"] = consent
    athlete_focus = st.text_input(
        "Optional focus",
        placeholder="Example: Decide whether to run intervals tomorrow or stay easy.",
        disabled=not consent,
    )
    generate = st.button("Generate smart insights", disabled=not consent)
    if generate:
        with st.spinner("Generating Active Intelligence..."):
            payload = generate_active_intelligence(
                bundle.user,
                bundle.activities,
                bundle.health_metrics,
                nutrition_entries,
                snapshot,
                athlete_focus,
            )
        st.session_state["active_intelligence_payload"] = payload

    payload = st.session_state.get("active_intelligence_payload")
    if payload:
        provider = escape(str(payload.get("provider") or "configured LLM"))
        model_name = escape(str(payload.get("model_name") or ""))
        st.info(f"Generated by {provider}{f' / {model_name}' if model_name else ''}. Garmin-like insights are available here after generation.")
        if payload.get("summary"):
            st.write(payload["summary"])
        insights = payload.get("insights") or []
        for index in range(0, len(insights), 2):
            columns = st.columns(2)
            for column, insight in zip(columns, insights[index : index + 2], strict=False):
                with column:
                    evidence = insight.get("evidence") or []
                    evidence_html = "".join(f"<li>{escape(str(item))}</li>" for item in evidence[:3])
                    st.markdown(
                        f"""
                        <div class="premium-card">
                            <span class="premium-status">{escape(str(insight.get("status", "stable")))}</span>
                            <h3>{escape(str(insight.get("title", "Insight")))}</h3>
                            <p>{escape(str(insight.get("message", "")))}</p>
                            <p class="premium-muted">{escape(str(insight.get("action", "")))}</p>
                            <ul>{evidence_html}</ul>
                            <p class="premium-muted">Confidence: {float(insight.get("confidence") or 0):.0f}%</p>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
        if payload.get("next_check_in"):
            st.caption(f"Next check-in: {payload['next_check_in']}")
        if payload.get("limitations"):
            with st.expander("Limitations"):
                for item in payload["limitations"]:
                    st.write(f"- {item}")
        return

    cards = build_active_intelligence_cards(snapshot, nutrition_entries)
    st.caption("Local fallback cards generated without an LLM request.")
    for index in range(0, len(cards), 2):
        columns = st.columns(2)
        for column, card in zip(columns, cards[index : index + 2], strict=False):
            with column:
                st.markdown(
                    f"""
                    <div class="premium-card">
                        <span class="premium-status">{escape(card.status)}</span>
                        <h3>{escape(card.title)}</h3>
                        <p>{escape(card.message)}</p>
                        <p class="premium-muted">{escape(card.action)}</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


def _render_performance_dashboard(bundle, nutrition_entries: pd.DataFrame) -> None:
    daily = _daily_performance_frame(bundle.activities, bundle.health_metrics, nutrition_entries)
    metric_options = [
        "distance_km",
        "duration_min",
        "avg_hr",
        "elevation_m",
        "sleep_score",
        "sleep_duration",
        "resting_hr",
        "hrv",
        "stress",
        "body_battery",
        "recovery_time",
        "vo2max",
        "calories",
        "protein_g",
        "carbs_g",
        "fat_g",
    ]
    available = [metric for metric in metric_options if metric in daily.columns]
    controls = st.columns([1, 2])
    days = controls[0].selectbox("Period", options=[30, 60, 90, 180, 365], index=2, format_func=lambda value: f"{value} days")
    selected_metrics = controls[1].multiselect(
        "Metrics",
        options=available,
        default=[metric for metric in ("distance_km", "sleep_score", "vo2max", "calories") if metric in available],
    )
    filtered = _filter_period(daily, int(days))
    st.plotly_chart(_custom_metric_chart(filtered, selected_metrics), width="stretch")
    st.plotly_chart(_correlation_chart(filtered, selected_metrics), width="stretch")
    st.dataframe(filtered.tail(30), width="stretch")


def _render_training_guidance(snapshot: dict) -> None:
    guidance = build_training_guidance(snapshot)
    metrics = st.columns(4)
    metrics[0].metric("Readiness", format_metric_number(snapshot["readiness"]["score"], decimals=0), snapshot["readiness"]["label"])
    metrics[1].metric("Fatigue", format_metric_number(snapshot["fatigue"]["score"], decimals=0), snapshot["fatigue"]["level"])
    metrics[2].metric("7d Mileage", f"{snapshot['weekly_mileage']['7d']:.1f} km")
    metrics[3].metric("Long Run", f"{snapshot['long_runs']['latest_long_run_km']:.1f} km")
    for index in range(0, len(guidance), 2):
        columns = st.columns(2)
        for column, item in zip(columns, guidance[index : index + 2], strict=False):
            with column:
                st.markdown(
                    f"""
                    <div class="premium-card">
                        <span class="premium-status">Guidance</span>
                        <h3>{escape(item["title"])}</h3>
                        <p>{escape(item["guidance"])}</p>
                        <p class="premium-muted">{escape(item["why"])}</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


def _render_3d_maps(bundle) -> None:
    settings = get_settings()
    activities = bundle.activities.copy()
    if activities.empty:
        st.info("No activities are available yet.")
        return
    activities["date"] = pd.to_datetime(activities["date"])
    runs = running_activities(activities)
    activity_pool = runs if not runs.empty else activities
    options = {
        f"{row.id} | {row.date:%Y-%m-%d} | {row.type} | {row.distance:.2f} km": int(row.id)
        for row in activity_pool.sort_values("date", ascending=False).itertuples()
    }
    selected_label = st.selectbox("Activity", list(options.keys()))
    selected_id = options[selected_label]
    activity = activities.loc[activities["id"] == selected_id].iloc[0]
    track_points = _load_track_points(selected_id)
    has_gps = not track_points[["latitude", "longitude"]].dropna().empty
    if has_gps:
        st.caption("Google Maps 3D-style tilted hybrid route view using stored Garmin GPS points.")
        render_activity_route_map(
            track_points,
            api_key=settings.google_maps_api_key,
            map_id=settings.google_maps_map_id,
            muted_color=MUTED,
        )
        with st.expander("Fallback elevation view"):
            st.plotly_chart(_route_3d_chart(track_points, activity), width="stretch")
    else:
        st.caption("This activity does not have GPS points. Showing an elevation-style 3D model from activity summary data.")
        st.plotly_chart(_route_3d_chart(track_points, activity), width="stretch")
    cols = st.columns(4)
    cols[0].metric("Distance", f"{float(activity.get('distance') or 0):.2f} km")
    cols[1].metric("Duration", format_duration_minutes(float(activity.get("duration") or 0)))
    cols[2].metric("Pace", format_pace(float(activity["pace"])) if pd.notna(activity.get("pace")) else "n/a")
    cols[3].metric("Elevation", format_metric_number(activity.get("elevation"), decimals=0, suffix=" m"))


def _render_nutrition(bundle, nutrition_entries: pd.DataFrame) -> None:
    target_date = st.date_input("Nutrition date", value=date.today())
    targets = estimate_nutrition_targets(bundle.user, bundle.activities, target_date)
    day_entries = nutrition_entries.copy()
    if not day_entries.empty:
        day_entries["entry_date"] = pd.to_datetime(day_entries["entry_date"])
        day_entries = day_entries[day_entries["entry_date"].dt.date == target_date]
    consumed = {
        "calories": float(day_entries["calories"].sum()) if not day_entries.empty else 0.0,
        "protein_g": float(day_entries["protein_g"].sum()) if not day_entries.empty else 0.0,
        "carbs_g": float(day_entries["carbs_g"].sum()) if not day_entries.empty else 0.0,
        "fat_g": float(day_entries["fat_g"].sum()) if not day_entries.empty else 0.0,
    }
    cols = st.columns(4)
    cols[0].metric("Calories", f"{consumed['calories']:.0f}", f"target {targets.calories:.0f}")
    cols[1].metric("Protein", f"{consumed['protein_g']:.0f} g", f"target {targets.protein_g:.0f} g")
    cols[2].metric("Carbs", f"{consumed['carbs_g']:.0f} g", f"target {targets.carbs_g:.0f} g")
    cols[3].metric("Fat", f"{consumed['fat_g']:.0f} g", f"target {targets.fat_g:.0f} g")

    with st.form("nutrition_entry_form"):
        form_cols = st.columns([1, 1.4, 1, 1, 1, 1])
        meal_type = form_cols[0].selectbox("Meal", ["breakfast", "lunch", "dinner", "snack", "fueling", "recovery"])
        food_name = form_cols[1].text_input("Food", placeholder="Rice bowl, banana, protein shake")
        calories = form_cols[2].number_input("kcal", min_value=0.0, max_value=5000.0, value=0.0, step=25.0)
        protein = form_cols[3].number_input("Protein g", min_value=0.0, max_value=400.0, value=0.0, step=1.0)
        carbs = form_cols[4].number_input("Carbs g", min_value=0.0, max_value=800.0, value=0.0, step=1.0)
        fat = form_cols[5].number_input("Fat g", min_value=0.0, max_value=300.0, value=0.0, step=1.0)
        notes = st.text_input("Notes", placeholder="Before tempo, post-long-run recovery, etc.")
        submit = st.form_submit_button("Add nutrition")
    if submit:
        if not food_name.strip():
            st.error("Food name is required.")
        else:
            with session_scope() as session:
                repository.create_nutrition_entry(
                    session,
                    bundle.user.id,
                    {
                        "entry_date": target_date,
                        "meal_type": meal_type,
                        "food_name": food_name.strip(),
                        "calories": calories,
                        "protein_g": protein,
                        "carbs_g": carbs,
                        "fat_g": fat,
                        "notes": notes,
                    },
                )
            st.success("Nutrition entry added.")
            st.rerun()

    summary = daily_nutrition_summary(nutrition_entries)
    st.plotly_chart(_nutrition_chart(summary), width="stretch")
    if nutrition_entries.empty:
        st.caption("Nutrition entries will appear here after logging meals.")
    else:
        table = nutrition_entries.sort_values("entry_date", ascending=False).copy()
        table["entry_date"] = table["entry_date"].dt.date
        st.dataframe(
            table[["id", "entry_date", "meal_type", "food_name", "calories", "protein_g", "carbs_g", "fat_g", "notes"]],
            width="stretch",
        )
        delete_id = st.number_input("Delete entry id", min_value=0, value=0, step=1)
        if st.button("Delete nutrition entry", disabled=delete_id <= 0):
            with session_scope() as session:
                repository.delete_nutrition_entry(session, int(delete_id), bundle.user.id)
            st.success("Nutrition entry deleted.")
            st.rerun()


apply_dashboard_theme()
st.title("Connect+ Premium")
_premium_hero()

bundle = load_training_bundle()
with session_scope() as session:
    nutrition_entries = repository.nutrition_entries_dataframe(session, bundle.user.id)

if not nutrition_entries.empty:
    nutrition_entries["entry_date"] = pd.to_datetime(nutrition_entries["entry_date"])

tabs = st.tabs(["Active Intelligence", "Performance Dashboard", "Training Guidance", "3D Maps", "Nutrition"])
with tabs[0]:
    _render_active_intelligence(bundle, bundle.snapshot, nutrition_entries)
with tabs[1]:
    _render_performance_dashboard(bundle, nutrition_entries)
with tabs[2]:
    _render_training_guidance(bundle.snapshot)
with tabs[3]:
    _render_3d_maps(bundle)
with tabs[4]:
    _render_nutrition(bundle, nutrition_entries)
