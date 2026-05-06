"""Reusable Streamlit UI components."""

from __future__ import annotations

import json
from html import escape
from typing import Any

import streamlit as st

from utils.formatting import format_gap_minutes, format_goal_time, format_metric_number, format_pace


def apply_dashboard_theme() -> None:
    """Apply the dashboard visual system."""

    st.markdown(
        """
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@500;700;800&display=swap');

            :root {
                --coach-orange: #fc4c02;
                --coach-amber: #ffb000;
                --coach-ink: #111827;
                --coach-muted: #64748b;
                --coach-panel: rgba(255, 255, 255, 0.88);
                --coach-border: rgba(15, 23, 42, 0.10);
            }

            html, body, [class*="css"] {
                font-family: "Manrope", sans-serif;
            }

            .stApp {
                background:
                    radial-gradient(circle at 8% 8%, rgba(252, 76, 2, 0.16), transparent 28%),
                    radial-gradient(circle at 78% 10%, rgba(255, 176, 0, 0.14), transparent 30%),
                    linear-gradient(135deg, #fff7ed 0%, #f8fafc 42%, #eef2ff 100%);
                color: var(--coach-ink);
            }

            section[data-testid="stSidebar"] {
                background: linear-gradient(180deg, #111827 0%, #1f2937 100%);
            }

            section[data-testid="stSidebar"] * {
                color: #f9fafb !important;
            }

            section[data-testid="stSidebar"] input,
            section[data-testid="stSidebar"] textarea,
            section[data-testid="stSidebar"] [data-baseweb="select"] * {
                color: #111827 !important;
            }

            .block-container {
                padding-top: 1.8rem;
                max-width: 1280px;
            }

            h1, h2, h3 {
                letter-spacing: -0.04em;
            }

            div[data-testid="stMetric"] {
                background: var(--coach-panel);
                border: 1px solid var(--coach-border);
                border-radius: 22px;
                box-shadow: 0 18px 45px rgba(15, 23, 42, 0.08);
                padding: 18px 18px 16px;
            }

            div[data-testid="stMetricLabel"] p {
                color: var(--coach-muted);
                font-weight: 800;
                letter-spacing: 0.02em;
                text-transform: uppercase;
            }

            div[data-testid="stMetricValue"] {
                color: var(--coach-ink);
                font-weight: 800;
            }

            div[data-testid="stMetricDelta"] {
                color: var(--coach-orange);
                font-weight: 800;
            }

            .coach-hero {
                position: relative;
                overflow: hidden;
                border-radius: 30px;
                padding: 34px;
                margin-bottom: 24px;
                background:
                    linear-gradient(135deg, rgba(17, 24, 39, 0.96), rgba(30, 41, 59, 0.92)),
                    repeating-linear-gradient(135deg, transparent 0 16px, rgba(255, 255, 255, 0.08) 17px 18px);
                color: white;
                box-shadow: 0 26px 70px rgba(15, 23, 42, 0.24);
            }

            .coach-hero:after {
                content: "";
                position: absolute;
                width: 360px;
                height: 360px;
                right: -120px;
                top: -120px;
                border-radius: 50%;
                background: radial-gradient(circle, rgba(252, 76, 2, 0.92), rgba(252, 76, 2, 0));
            }

            .coach-eyebrow {
                position: relative;
                z-index: 1;
                display: inline-flex;
                align-items: center;
                gap: 8px;
                padding: 7px 12px;
                border-radius: 999px;
                background: rgba(252, 76, 2, 0.18);
                color: #fed7aa;
                font-size: 0.78rem;
                font-weight: 800;
                letter-spacing: 0.08em;
                text-transform: uppercase;
            }

            .coach-hero h1 {
                position: relative;
                z-index: 1;
                max-width: 760px;
                margin: 18px 0 8px;
                color: white;
                font-size: clamp(2.1rem, 5vw, 4.8rem);
                line-height: 0.94;
            }

            .coach-hero p {
                position: relative;
                z-index: 1;
                max-width: 720px;
                margin: 0;
                color: #cbd5e1;
                font-size: 1.08rem;
            }

            .coach-card {
                background: var(--coach-panel);
                border: 1px solid var(--coach-border);
                border-radius: 24px;
                box-shadow: 0 18px 45px rgba(15, 23, 42, 0.08);
                padding: 22px;
                height: 100%;
            }

            .coach-card strong {
                color: var(--coach-orange);
            }

            .coach-pill {
                display: inline-block;
                border-radius: 999px;
                padding: 6px 10px;
                background: rgba(252, 76, 2, 0.12);
                color: var(--coach-orange);
                font-size: 0.78rem;
                font-weight: 800;
                text-transform: uppercase;
                letter-spacing: 0.06em;
            }

            .coach-focus {
                margin-top: 14px;
                font-size: 1.25rem;
                font-weight: 800;
                letter-spacing: -0.03em;
            }

            .coach-muted {
                color: var(--coach-muted);
                margin-top: 6px;
            }

            div[data-testid="stPlotlyChart"] {
                background: rgba(255, 255, 255, 0.74);
                border: 1px solid var(--coach-border);
                border-radius: 24px;
                box-shadow: 0 18px 45px rgba(15, 23, 42, 0.07);
                padding: 10px;
            }

            div.stButton > button,
            div[data-testid="stFormSubmitButton"] button {
                border: 0;
                border-radius: 999px;
                background: linear-gradient(135deg, var(--coach-orange), #ff7a1a);
                color: white;
                font-weight: 800;
                box-shadow: 0 10px 24px rgba(252, 76, 2, 0.28);
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_dashboard_hero(user_name: str | None, motivation: str) -> None:
    """Render the dashboard hero section."""

    display_name = escape(user_name.strip()) if user_name else "Runner"
    safe_motivation = escape(motivation)
    st.markdown(
        f"""
        <section class="coach-hero">
            <div class="coach-eyebrow">Run dashboard</div>
            <h1>{display_name}, build the next strong week.</h1>
            <p>{safe_motivation}</p>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_focus_cards(snapshot: dict[str, Any]) -> None:
    """Render motivational focus cards."""

    weekly = snapshot["weekly_mileage"]
    long_run = snapshot["long_runs"]["latest_long_run_km"]
    fatigue = snapshot["fatigue"]
    readiness = snapshot["readiness"]
    current_7d = float(weekly.get("7d", 0.0))
    next_week_low = max(current_7d - 3, 0)
    next_week_high = current_7d + 5
    intensity = snapshot["intensity"]["distribution"]
    easy_minutes = float(intensity.get("Z2 / easy", 0.0))
    hard_minutes = float(intensity.get("Z4+ / hard", 0.0))
    focus = "Keep the aerobic floor high"
    if fatigue["level"] != "low":
        focus = "Absorb the work before adding more"
    elif long_run < 18:
        focus = "Extend the weekly long run"
    elif readiness["score"] >= 75:
        focus = "Use the good legs for one quality session"

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            f"""
            <div class="coach-card">
                <span class="coach-pill">This week</span>
                <div class="coach-focus">{next_week_low:.0f}-{next_week_high:.0f} km target range</div>
                <div class="coach-muted">Small progression keeps momentum without chasing a single big run.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f"""
            <div class="coach-card">
                <span class="coach-pill">Main focus</span>
                <div class="coach-focus">{focus}</div>
                <div class="coach-muted">Latest long run: <strong>{long_run:.1f} km</strong>.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            f"""
            <div class="coach-card">
                <span class="coach-pill">Intensity balance</span>
                <div class="coach-focus">{easy_minutes:.0f} easy min / {hard_minutes:.0f} hard min</div>
                <div class="coach-muted"></div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_overview_metrics(snapshot: dict[str, Any]) -> None:
    """Render top-level dashboard metrics."""

    weekly = snapshot["weekly_mileage"]
    recovery = snapshot["recovery"]
    prediction = snapshot.get("active_goal_projection") or snapshot["prediction"]
    vo2 = snapshot["vo2max"]
    goal_label = "Goal Confidence"

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Mileage (7d)", f"{weekly['7d']:.1f} km", f"28d: {weekly['28d']:.1f} km")
    col2.metric("VO2max", format_metric_number(vo2.get("latest"), decimals=1), vo2["trend"])
    col3.metric("Readiness", format_metric_number(snapshot["readiness"]["score"], decimals=0), snapshot["readiness"]["label"])
    finish_minutes = prediction.get("predicted_time_minutes", prediction.get("predicted_minutes"))
    col4.metric("Predicted Finish", format_goal_time(finish_minutes), format_gap_minutes(prediction["gap_minutes"]))

    col5, col6, col7 = st.columns(3)
    col5.metric("Recovery Time", format_metric_number(recovery.get("recovery_time"), decimals=0, suffix=" h"))
    col6.metric("Sleep Score", format_metric_number(recovery.get("sleep_score"), decimals=0))
    col7.metric(goal_label, format_metric_number(prediction["confidence"], decimals=0, suffix="%"))


def render_warning_list(rules: list[str]) -> None:
    """Render alert and recommendation bullets."""

    if not rules:
        st.success("No rule-based warnings right now.")
        return
    for rule in rules:
        st.warning(rule)


def parse_recommendation_blob(raw_text: str) -> dict[str, Any]:
    """Parse stored recommendation JSON."""

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        return {"explanation": raw_text}


def render_coaching_card(coaching: dict[str, Any], title: str) -> None:
    """Render a coaching recommendation block."""

    st.subheader(title)
    if coaching.get("goal_name"):
        st.caption(f"Active goal: {coaching.get('goal_name')} ({coaching.get('goal_label', coaching.get('goal_type', ''))})")
    if coaching.get("summary"):
        st.write(coaching["summary"])
    if coaching.get("goal_alignment"):
        st.caption(coaching["goal_alignment"])
    if coaching.get("yesterday_assessment"):
        st.write(f"Yesterday: {coaching['yesterday_assessment']}")
    st.write(f"Tomorrow: {coaching.get('tomorrow_recommendation', coaching.get('daily_advice', 'n/a'))}")
    st.write(f"This week: {coaching.get('weekly_outlook', coaching.get('weekly_advice', 'n/a'))}")
    st.write(f"Readiness: {coaching.get('readiness_assessment', 'n/a')}")
    confidence = coaching.get("confidence", coaching.get("confidence_to_sub4", 0))
    st.write(f"Confidence: {float(confidence):.0f}%")
    if coaching.get("priority"):
        st.write(f"Priority: {coaching['priority']}")
    if coaching.get("evidence"):
        st.caption("Evidence")
        for item in coaching["evidence"]:
            st.write(f"- {item}")

    effectiveness = coaching.get("training_effectiveness")
    if isinstance(effectiveness, dict) and effectiveness:
        status = str(effectiveness.get("status", "n/a")).title()
        st.write(f"Training effectiveness: {status}")
        st.write(effectiveness.get("summary", "n/a"))
        working = effectiveness.get("working") or []
        if working:
            st.caption("What is working")
            for item in working:
                st.write(f"- {item}")
        limiters = effectiveness.get("limiters") or []
        if limiters:
            st.caption("What is limiting progress")
            for item in limiters:
                st.write(f"- {item}")

    if coaching.get("explanation"):
        st.write(f"Overall explanation: {coaching.get('explanation', 'n/a')}")
    preview_title = coaching.get("message_title", coaching.get("email_subject"))
    if preview_title:
        st.caption(f"Telegram preview: {preview_title}")
    if coaching.get("rule_recommendations"):
        st.caption("Rule-based checks applied first")
        for recommendation in coaching["rule_recommendations"]:
            st.write(f"- {recommendation}")


def render_goal_summary(goal_pace: float, predicted_pace: float, predicted_finish_minutes: float) -> None:
    """Render a goal summary."""

    col1, col2, col3 = st.columns(3)
    col1.metric("Goal Pace", format_pace(goal_pace))
    col2.metric("Predicted Pace", format_pace(predicted_pace))
    col3.metric("Predicted Finish", format_goal_time(predicted_finish_minutes))
