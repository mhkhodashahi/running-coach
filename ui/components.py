"""Reusable Streamlit UI components."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from html import escape
from typing import Any

import streamlit as st

from utils.formatting import format_gap_minutes, format_goal_time, format_metric_number, format_pace


def apply_dashboard_theme() -> None:
    """Apply the dashboard visual system."""

    st.markdown(
        """
        <style>
            @import url('https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700&family=Sora:wght@500;600;700;800&display=swap');

            :root {
                --coach-accent: #D4FF3A;
                --coach-accent-soft: rgba(212, 255, 58, 0.14);
                --coach-bg: #0A0D14;
                --coach-panel: #121722;
                --coach-panel-2: #1A2030;
                --coach-border: #1F2534;
                --coach-border-strong: #2A3245;
                --coach-ink: #F2F4F8;
                --coach-muted: #9AA3B5;
                --coach-soft: #C9D0DC;
                --coach-green: #34D399;
                --coach-teal: #2DD4BF;
                --coach-blue: #38BDF8;
                --coach-purple: #A78BFA;
                --coach-amber: #FBBF24;
                --coach-orange: #FB923C;
                --coach-red: #FF7A8A;
            }

            html, body, [class*="css"] {
                font-family: "DM Sans", system-ui, sans-serif;
            }

            .stApp {
                background: var(--coach-bg);
                color: var(--coach-ink);
            }

            section[data-testid="stSidebar"] {
                background: var(--coach-bg);
                border-right: 1px solid var(--coach-border);
                min-width: 220px;
                max-width: 260px;
            }

            section[data-testid="stSidebar"] * {
                color: var(--coach-soft) !important;
            }

            section[data-testid="stSidebar"] > div:first-child {
                padding: 28px 18px;
            }

            section[data-testid="stSidebar"] > div:first-child::before {
                content: "Running Coach";
                display: flex;
                align-items: center;
                min-height: 38px;
                margin: 0 6px 28px;
                padding-left: 48px;
                color: var(--coach-ink);
                font-family: "Sora", system-ui, sans-serif;
                font-size: 18px;
                font-weight: 700;
                letter-spacing: -0.2px;
                background:
                    linear-gradient(var(--coach-accent), var(--coach-accent)) left center / 38px 38px no-repeat;
                border-radius: 12px;
            }

            .coach-sidebar-sync {
                display: flex;
                align-items: center;
                gap: 12px;
                margin-top: 18px;
                padding: 12px 14px;
                font-size: 13px;
                line-height: 1.5;
                background: var(--coach-panel);
                border: 1px solid var(--coach-border);
                border-radius: 14px;
            }

            .coach-sidebar-sync .coach-sync-dot {
                width: 8px;
                height: 8px;
                flex: none;
                border-radius: 50%;
                background: var(--coach-green);
                box-shadow: 0 0 0 4px rgba(52, 211, 153, 0.18);
            }

            .coach-sidebar-sync.is-unsynced .coach-sync-dot {
                background: var(--coach-muted);
                box-shadow: 0 0 0 4px rgba(154, 163, 181, 0.14);
            }

            .coach-sidebar-sync .coach-sync-copy {
                color: var(--coach-muted) !important;
                overflow-wrap: anywhere;
            }

            section[data-testid="stSidebar"] input,
            section[data-testid="stSidebar"] textarea,
            section[data-testid="stSidebar"] [data-baseweb="select"] * {
                color: var(--coach-ink) !important;
                background: var(--coach-panel-2) !important;
            }

            section[data-testid="stSidebar"] [data-testid="stSidebarNav"] {
                padding: 0;
            }

            section[data-testid="stSidebar"] [data-testid="stSidebarNav"] ul {
                display: flex;
                flex-direction: column;
                gap: 4px;
                padding: 0;
            }

            section[data-testid="stSidebar"] [data-testid="stSidebarNav"] li {
                margin: 0;
            }

            section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a {
                display: flex;
                align-items: center;
                gap: 12px;
                min-height: 44px;
                padding: 0 14px;
                border-radius: 12px;
                color: #B4BCCB !important;
                font-weight: 500;
                text-decoration: none;
            }

            section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a:hover {
                background: var(--coach-panel);
                color: var(--coach-ink) !important;
            }

            section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="page"] {
                background: var(--coach-accent) !important;
                color: var(--coach-bg) !important;
                font-weight: 700;
            }

            section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="page"] * {
                color: var(--coach-bg) !important;
            }

            section[data-testid="stSidebar"] hr {
                border-color: var(--coach-border);
            }

            section[data-testid="stSidebar"] details[data-testid="stExpander"] {
                background: var(--coach-panel);
                border: 1px solid var(--coach-border);
                border-radius: 14px;
                overflow: hidden;
                margin-top: 10px;
            }

            section[data-testid="stSidebar"] details[data-testid="stExpander"] summary {
                min-height: 44px;
                padding: 0 14px;
                color: #B4BCCB !important;
                font-weight: 600;
            }

            section[data-testid="stSidebar"] details[data-testid="stExpander"] summary:hover {
                background: var(--coach-panel-2);
                color: var(--coach-ink) !important;
            }

            section[data-testid="stSidebar"] details[data-testid="stExpander"] div[data-testid="stExpanderDetails"] {
                border-top: 1px solid var(--coach-border);
                padding: 12px 14px 16px;
            }

            .block-container {
                padding-top: 1.8rem;
                max-width: 1280px;
            }

            h1, h2, h3 {
                color: var(--coach-ink);
                font-family: "Sora", system-ui, sans-serif;
                letter-spacing: -0.02em;
            }

            p, li, label, span, div {
                color: inherit;
            }

            div[data-testid="stMetric"] {
                background: var(--coach-panel);
                border: 1px solid var(--coach-border);
                border-radius: 18px;
                box-shadow: none;
                padding: 18px 18px 16px;
            }

            div[data-testid="stMetricLabel"] p {
                color: var(--coach-muted);
                font-weight: 700;
                letter-spacing: 0;
            }

            div[data-testid="stMetricValue"] {
                color: var(--coach-ink);
                font-weight: 800;
                font-family: "Sora", system-ui, sans-serif;
            }

            div[data-testid="stMetricDelta"] {
                color: var(--coach-accent);
                font-weight: 700;
            }

            .coach-hero {
                padding: 0;
                margin-bottom: 18px;
                background: transparent;
                color: var(--coach-ink);
                box-shadow: none;
            }

            .coach-eyebrow {
                display: inline-flex;
                align-items: center;
                gap: 8px;
                color: var(--coach-muted);
                font-size: 13px;
                font-weight: 700;
                letter-spacing: 1px;
                text-transform: uppercase;
            }

            .coach-hero h1 {
                max-width: 760px;
                margin: 6px 0 0;
                color: var(--coach-ink);
                font-size: clamp(2rem, 4vw, 2.6rem);
                line-height: 1.1;
                font-weight: 700;
            }

            .coach-hero p {
                max-width: 720px;
                margin: 10px 0 0;
                color: var(--coach-muted);
                font-size: 1rem;
            }

            .coach-card {
                background: var(--coach-panel);
                border: 1px solid var(--coach-border);
                border-radius: 18px;
                box-shadow: none;
                padding: 20px;
                height: 100%;
            }

            .coach-card strong {
                color: var(--coach-accent);
            }

            .coach-card-accent {
                position: relative;
                overflow: hidden;
                background: var(--coach-accent);
                border: 1px solid var(--coach-accent);
                border-radius: 24px;
                color: var(--coach-bg);
                padding: 28px 32px;
            }

            .coach-card-accent .coach-muted,
            .coach-card-accent .coach-focus {
                color: var(--coach-bg);
            }

            .coach-pill {
                display: inline-block;
                border-radius: 999px;
                padding: 6px 10px;
                background: var(--coach-accent-soft);
                color: var(--coach-accent);
                font-size: 12px;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.8px;
            }

            .coach-card-accent .coach-pill {
                background: var(--coach-bg);
                color: var(--coach-accent);
            }

            .coach-focus {
                margin-top: 14px;
                color: var(--coach-ink);
                font-family: "Sora", system-ui, sans-serif;
                font-size: 1.25rem;
                font-weight: 800;
                letter-spacing: -0.02em;
            }

            .coach-muted {
                color: var(--coach-muted);
                margin-top: 6px;
            }

            .coach-kpi-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                gap: 10px;
                margin-top: 16px;
            }

            .coach-kpi {
                background: rgba(10, 13, 20, 0.92);
                border-radius: 14px;
                padding: 12px 14px;
                color: var(--coach-ink);
            }

            .coach-kpi-label {
                color: var(--coach-muted);
                font-size: 12px;
            }

            .coach-kpi-value {
                color: var(--coach-ink);
                font-size: 15px;
                font-weight: 700;
            }

            div[data-testid="stPlotlyChart"] {
                background: var(--coach-panel);
                border: 1px solid var(--coach-border);
                border-radius: 24px;
                box-shadow: none;
                padding: 10px;
            }

            div.stButton > button,
            div[data-testid="stFormSubmitButton"] button {
                border: 0;
                border-radius: 12px;
                background: var(--coach-accent);
                color: var(--coach-bg);
                font-weight: 700;
                box-shadow: none;
            }

            div[data-testid="stAlert"] {
                background: var(--coach-panel-2);
                border: 1px solid var(--coach-border);
                border-radius: 16px;
                color: var(--coach-ink);
            }

            div[data-testid="stDataFrame"] {
                background: var(--coach-panel);
                border-radius: 18px;
                border: 1px solid var(--coach-border);
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_sync_status(last_synced_at: datetime | None, last_activity_date: date | None) -> None:
    if last_synced_at is None:
        sync_label = "Garmin sync: Never"
    else:
        local_time = last_synced_at.replace(tzinfo=UTC).astimezone()
        sync_label = f"Garmin synced {local_time:%d %b %Y, %H:%M}"
    activity_label = (
        f"Last activity {last_activity_date:%d %b %Y}" if last_activity_date else "Last activity: None yet"
    )
    state_class = "" if last_synced_at else " is-unsynced"
    st.markdown(
        f'<div class="coach-sidebar-sync{state_class}">'
        '<span class="coach-sync-dot" aria-hidden="true"></span>'
        f'<span class="coach-sync-copy">{escape(sync_label)}<br>{escape(activity_label)}</span>'
        "</div>",
        unsafe_allow_html=True,
    )


def render_dashboard_hero(user_name: str | None, motivation: str) -> None:
    """Render the dashboard hero section."""

    display_name = escape(user_name.strip()) if user_name else "Runner"
    safe_motivation = escape(motivation)
    st.markdown(
        f"""
        <section class="coach-hero">
            <div class="coach-eyebrow">Today</div>
            <h1>Good morning, {display_name}</h1>
            <p>{safe_motivation}</p>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_today_status(snapshot: dict[str, Any]) -> None:
    """Render a plain-language body status panel."""

    readiness = snapshot["readiness"]
    fatigue = snapshot["fatigue"]
    recovery = snapshot["recovery"]
    weekly = snapshot["weekly_mileage"]
    readiness_score = float(readiness.get("score", 0.0))
    fatigue_level = str(fatigue.get("level", "low"))
    sleep_score = float(recovery.get("sleep_score") or 0.0)
    recovery_time = float(recovery.get("recovery_time") or 0.0)
    body_battery = float(recovery.get("body_battery") or 0.0)

    if fatigue_level == "high" or readiness_score < 45 or recovery_time >= 36:
        status = "Easy movement or rest"
        badge = "Recovery day"
        recommendation = "Stay easy today. Your body is still absorbing load, so skip intensity until recovery signals improve."
    elif fatigue_level == "moderate" or readiness_score < 65 or sleep_score < 72:
        status = "Easy 30-40 min"
        badge = "Build carefully"
        recommendation = "Keep effort comfortable and stop before the session becomes a workout."
    elif readiness_score >= 75:
        status = "Training window open"
        badge = "Ready"
        recommendation = "A focused workout can fit today if the schedule and soreness agree."
    else:
        status = "Steady aerobic day"
        badge = "Maintain"
        recommendation = "Keep the week steady and avoid adding intensity just because one metric looks good."

    st.markdown(
        f"""
        <div class="coach-card-accent">
            <span class="coach-pill">{escape(badge)}</span>
            <div class="coach-focus">{escape(status)}</div>
            <div class="coach-muted">{escape(recommendation)}</div>
            <div class="coach-kpi-grid">
                <div class="coach-kpi">
                    <div class="coach-kpi-label">Readiness</div>
                    <div class="coach-kpi-value">{readiness_score:.0f}/100 · {escape(str(readiness.get("label", "n/a")))}</div>
                </div>
                <div class="coach-kpi">
                    <div class="coach-kpi-label">Sleep and battery</div>
                    <div class="coach-kpi-value">{sleep_score:.0f} sleep · {body_battery:.0f} battery</div>
                </div>
                <div class="coach-kpi">
                    <div class="coach-kpi-label">Running · last 7 days</div>
                    <div class="coach-kpi-value">{float(weekly.get("7d", 0.0)):.1f} km</div>
                </div>
                <div class="coach-kpi">
                    <div class="coach-kpi-label">Recovery time</div>
                    <div class="coach-kpi-value">{recovery_time:.0f} h</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_focus_cards(snapshot: dict[str, Any]) -> None:
    """Render overall health and training focus cards."""

    weekly = snapshot["weekly_mileage"]
    long_run = snapshot["long_runs"]["latest_long_run_km"]
    fatigue = snapshot["fatigue"]
    readiness = snapshot["readiness"]
    recovery = snapshot["recovery"]
    current_7d = float(weekly.get("7d", 0.0))
    next_week_low = max(current_7d - 3, 0)
    next_week_high = current_7d + 5
    intensity = snapshot["intensity"]["distribution"]
    easy_minutes = float(intensity.get("Z2 / easy", 0.0))
    hard_minutes = float(intensity.get("Z4+ / hard", 0.0))
    focus = "Keep health signals stable"
    if fatigue["level"] != "low":
        focus = "Absorb the work before adding more"
    elif float(recovery.get("sleep_score") or 0.0) < 72:
        focus = "Make sleep the main training lever"
    elif readiness["score"] >= 75:
        focus = "Use the good body signals wisely"

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            f"""
            <div class="coach-card">
                <span class="coach-pill">Weekly balance</span>
                <div class="coach-focus">{next_week_low:.0f}-{next_week_high:.0f} km target range</div>
                <div class="coach-muted">Keep total load controlled before chasing speed.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f"""
            <div class="coach-card">
                <span class="coach-pill">Body focus</span>
                <div class="coach-focus">{focus}</div>
                <div class="coach-muted">Latest long run still matters, but it is one signal: <strong>{long_run:.1f} km</strong>.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            f"""
            <div class="coach-card">
                <span class="coach-pill">Intensity mix</span>
                <div class="coach-focus">{easy_minutes:.0f} easy min / {hard_minutes:.0f} hard min</div>
                <div class="coach-muted">Easy volume supports recovery; hard volume needs a reason.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_overview_metrics(snapshot: dict[str, Any]) -> None:
    """Render health-first dashboard metrics."""

    weekly = snapshot["weekly_mileage"]
    recovery = snapshot["recovery"]
    prediction = snapshot.get("active_goal_projection") or snapshot["prediction"]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Readiness", format_metric_number(snapshot["readiness"]["score"], decimals=0), snapshot["readiness"]["label"])
    col2.metric("Sleep Score", format_metric_number(recovery.get("sleep_score"), decimals=0))
    col3.metric("Body Battery", format_metric_number(recovery.get("body_battery"), decimals=0))
    col4.metric("Recovery Time", format_metric_number(recovery.get("recovery_time"), decimals=0, suffix=" h"))

    col5, col6, col7 = st.columns(3)
    col5.metric("Running · Last 7 Days", f"{weekly['7d']:.1f} km", f"28d: {weekly['28d']:.1f} km")
    col6.metric("HRV", format_metric_number(recovery.get("hrv"), decimals=0, suffix=" ms"))
    finish_minutes = prediction.get("predicted_time_minutes", prediction.get("predicted_minutes"))
    col7.metric("Goal Projection", format_goal_time(finish_minutes), format_gap_minutes(prediction["gap_minutes"]))


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
