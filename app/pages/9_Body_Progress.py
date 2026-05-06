"""Body progress timeline and avatar page."""

from __future__ import annotations

import json
from datetime import date
from html import escape
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import text

from body_progress.avatar import build_avatar_state
from body_progress.domain import BodyScanSummary
from body_progress.insight_sql import (
    BODY_SCAN_INSIGHTS_CREATE_TABLE_SQL,
    BODY_SCAN_INSIGHTS_DATE_INDEX_SQL,
    BODY_SCAN_INSIGHTS_USER_INDEX_SQL,
)
from body_progress.sql import (
    BODY_SCANS_CREATE_TABLE_SQL,
    BODY_SCANS_DATE_INDEX_SQL,
    BODY_SCANS_INDEX_SQL,
)
from config import get_settings
from db import repository
from db.session import session_scope
from services.body_progress_service import BodyProgressService
from services.body_scan_insight_service import BodyScanInsightService
from ui.components import apply_dashboard_theme
from utils.bootstrap import load_training_bundle

VIEW_OPTIONS = {
    "Front": "front",
    "Side": "side",
    "Back": "back",
    "Running form": "running_form",
    "Other": "other",
}


def _body_scans_dataframe(session, user_id: int) -> pd.DataFrame:
    session.execute(text(BODY_SCANS_CREATE_TABLE_SQL))
    session.execute(text(BODY_SCANS_INDEX_SQL))
    session.execute(text(BODY_SCANS_DATE_INDEX_SQL))
    if hasattr(repository, "body_scans_dataframe"):
        return repository.body_scans_dataframe(session, user_id)

    query = text(
        """
        SELECT id, user_id, scan_date, view, status, source_image_path,
               preview_image_path, mesh_path, keypoints_json, measurements_json,
               pose_quality, processor_name,
               error_message, consent_to_store_image, notes, created_at, updated_at
        FROM body_scans
        WHERE user_id = :user_id
        ORDER BY scan_date ASC, created_at ASC
        """
    )
    df = pd.read_sql_query(query, session.bind, params={"user_id": user_id})
    if not df.empty:
        for column in ("scan_date", "created_at", "updated_at"):
            df[column] = pd.to_datetime(df[column])
    return df


def _body_scan_summaries(scans_df: pd.DataFrame) -> list[BodyScanSummary]:
    if scans_df.empty:
        return []
    summaries: list[BodyScanSummary] = []
    for row in scans_df.itertuples():
        summaries.append(
            BodyScanSummary(
                id=int(row.id),
                user_id=int(row.user_id),
                scan_date=pd.Timestamp(row.scan_date).date(),
                view=row.view,
                status=row.status,
                source_image_path=row.source_image_path,
                preview_image_path=row.preview_image_path,
                mesh_path=row.mesh_path,
                pose_quality=row.pose_quality if pd.notna(row.pose_quality) else None,
                notes=row.notes,
                created_at=pd.Timestamp(row.created_at).to_pydatetime(),
            )
        )
    return summaries


def _body_scan_insights_dataframe(session, user_id: int) -> pd.DataFrame:
    session.execute(text(BODY_SCAN_INSIGHTS_CREATE_TABLE_SQL))
    session.execute(text(BODY_SCAN_INSIGHTS_USER_INDEX_SQL))
    session.execute(text(BODY_SCAN_INSIGHTS_DATE_INDEX_SQL))
    if hasattr(repository, "body_scan_insights_dataframe"):
        return repository.body_scan_insights_dataframe(session, user_id)

    query = text(
        """
        SELECT id, user_id, insight_date, scan_ids_json, summary, payload_json,
               prompt_context_json, model_provider, model_name, created_at
        FROM body_scan_insights
        WHERE user_id = :user_id
        ORDER BY insight_date DESC, created_at DESC
        """
    )
    df = pd.read_sql_query(query, session.bind, params={"user_id": user_id})
    if not df.empty:
        for column in ("insight_date", "created_at"):
            df[column] = pd.to_datetime(df[column])
    return df


def _body_progress_css() -> None:
    st.markdown(
        """
        <style>
            .body-lab-hero {
                border-radius: 30px;
                padding: 30px;
                color: white;
                background:
                    radial-gradient(circle at 82% 16%, rgba(252, 76, 2, .72), transparent 30%),
                    linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
                box-shadow: 0 26px 70px rgba(15, 23, 42, 0.22);
                margin-bottom: 22px;
            }
            .body-lab-hero h1 {
                color: white;
                font-size: clamp(2.1rem, 4.5vw, 4.4rem);
                line-height: .95;
                margin: 12px 0 8px;
            }
            .body-lab-hero p {
                color: #cbd5e1;
                max-width: 780px;
            }
            .avatar-card {
                min-height: 430px;
                border-radius: 30px;
                padding: 26px;
                background:
                    radial-gradient(circle at 50% 16%, rgba(252, 76, 2, .18), transparent 24%),
                    linear-gradient(180deg, rgba(255,255,255,.92), rgba(248,250,252,.84));
                border: 1px solid rgba(15, 23, 42, .10);
                box-shadow: 0 18px 45px rgba(15, 23, 42, .08);
                text-align: center;
            }
            .avatar-figure {
                position: relative;
                width: 190px;
                height: 270px;
                margin: 18px auto 12px;
            }
            .avatar-head {
                position: absolute;
                top: 0;
                left: 70px;
                width: 50px;
                height: 50px;
                border-radius: 50%;
                background: var(--avatar-color);
                box-shadow: 0 12px 28px rgba(15,23,42,.18);
            }
            .avatar-torso {
                position: absolute;
                top: 58px;
                left: 50px;
                width: 90px;
                height: 116px;
                border-radius: 42px 42px 32px 32px;
                background: linear-gradient(180deg, var(--avatar-color), #111827);
            }
            .avatar-arm, .avatar-leg {
                position: absolute;
                background: #111827;
                border-radius: 999px;
                transform-origin: top center;
            }
            .avatar-arm.left { top: 70px; left: 38px; width: 18px; height: 98px; transform: rotate(17deg); }
            .avatar-arm.right { top: 70px; right: 38px; width: 18px; height: 98px; transform: rotate(-17deg); }
            .avatar-leg.left { top: 166px; left: 68px; width: 22px; height: 108px; transform: rotate(9deg); }
            .avatar-leg.right { top: 166px; right: 68px; width: 22px; height: 108px; transform: rotate(-9deg); }
            .avatar-title {
                color: #111827;
                font-weight: 900;
                font-size: 1.55rem;
                letter-spacing: -.04em;
            }
            .avatar-subtitle {
                color: #64748b;
                margin: 4px 0 18px;
            }
            .avatar-chip-row {
                display: grid;
                grid-template-columns: 1fr;
                gap: 8px;
            }
            .avatar-chip {
                border-radius: 999px;
                background: rgba(15, 23, 42, .06);
                padding: 9px 12px;
                color: #111827;
                font-weight: 800;
                font-size: .86rem;
            }
            .sam-avatar-card {
                border-radius: 30px;
                padding: 22px;
                background:
                    radial-gradient(circle at 80% 10%, rgba(252, 76, 2, .20), transparent 28%),
                    linear-gradient(180deg, rgba(255,255,255,.96), rgba(248,250,252,.88));
                border: 1px solid rgba(15, 23, 42, .10);
                box-shadow: 0 18px 45px rgba(15, 23, 42, .08);
            }
            .sam-avatar-topline {
                color: #9a3412;
                font-size: .76rem;
                font-weight: 950;
                text-transform: uppercase;
                letter-spacing: .09em;
                margin-bottom: 5px;
            }
            .sam-avatar-title {
                color: #111827;
                font-size: 1.45rem;
                font-weight: 950;
                letter-spacing: -.04em;
                line-height: 1;
            }
            .sam-avatar-subtitle {
                color: #64748b;
                margin: 8px 0 14px;
                font-size: .9rem;
            }
            .sam-avatar-silhouette {
                position: relative;
                height: 255px;
                width: 175px;
                margin: 10px auto 14px;
                filter: drop-shadow(0 24px 24px rgba(15,23,42,.16));
            }
            .sam-avatar-silhouette .head {
                position: absolute;
                left: 50%;
                top: 0;
                width: 48px;
                height: 48px;
                border-radius: 999px;
                transform: translateX(-50%);
                background: var(--sam-avatar-color);
            }
            .sam-avatar-silhouette .torso {
                position: absolute;
                left: 50%;
                top: 56px;
                width: calc(82px * var(--sam-width-scale));
                height: 118px;
                border-radius: 42px 42px 30px 30px;
                transform: translateX(-50%);
                background: linear-gradient(180deg, var(--sam-avatar-color), #111827);
            }
            .sam-avatar-silhouette .depth-shadow {
                position: absolute;
                left: 50%;
                top: 82px;
                width: calc(72px * var(--sam-depth-scale));
                height: 120px;
                border-radius: 999px;
                transform: translateX(-50%);
                background: rgba(252, 76, 2, .16);
            }
            .sam-avatar-silhouette .arm,
            .sam-avatar-silhouette .leg {
                position: absolute;
                background: #111827;
                border-radius: 999px;
                transform-origin: top center;
            }
            .sam-avatar-silhouette .arm.left { top: 72px; left: 33px; width: 16px; height: 94px; transform: rotate(16deg); }
            .sam-avatar-silhouette .arm.right { top: 72px; right: 33px; width: 16px; height: 94px; transform: rotate(-16deg); }
            .sam-avatar-silhouette .leg.left { top: 166px; left: 67px; width: 20px; height: 92px; transform: rotate(8deg); }
            .sam-avatar-silhouette .leg.right { top: 166px; right: 67px; width: 20px; height: 92px; transform: rotate(-8deg); }
            .sam-avatar-mesh-note {
                color: #475569;
                font-size: .78rem;
                margin-top: 8px;
                overflow-wrap: anywhere;
            }
            .scan-card {
                border-radius: 24px;
                background: rgba(255, 255, 255, .86);
                border: 1px solid rgba(15, 23, 42, .10);
                box-shadow: 0 18px 45px rgba(15, 23, 42, .08);
                overflow: hidden;
                height: 100%;
            }
            .scan-card-copy {
                padding: 14px 16px 16px;
            }
            .scan-card-copy strong {
                display: block;
                color: #111827;
                font-size: 1.05rem;
            }
            .scan-card-copy span {
                color: #64748b;
                font-size: .82rem;
                font-weight: 800;
                text-transform: uppercase;
            }
            .metric-chip-row {
                display: flex;
                flex-wrap: wrap;
                gap: 7px;
                margin-top: 10px;
            }
            .metric-chip {
                border-radius: 999px;
                background: rgba(252, 76, 2, .10);
                color: #9a3412;
                font-size: .74rem;
                font-weight: 900;
                padding: 6px 9px;
            }
            .shape-metric-panel {
                border-radius: 18px;
                background: rgba(15, 23, 42, .045);
                border: 1px solid rgba(15, 23, 42, .08);
                padding: 11px 12px;
                margin-top: 10px;
            }
            .shape-metric-title {
                color: #0f172a;
                font-size: .74rem;
                font-weight: 950;
                text-transform: uppercase;
                letter-spacing: .08em;
                margin-bottom: 8px;
            }
            .shape-metric-grid {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 8px;
            }
            .shape-metric {
                border-radius: 14px;
                background: rgba(255, 255, 255, .72);
                padding: 8px;
            }
            .shape-metric small {
                display: block;
                color: #64748b;
                font-size: .67rem;
                font-weight: 900;
                text-transform: uppercase;
            }
            .shape-metric strong {
                color: #0f172a;
                font-size: .94rem;
                font-weight: 950;
            }
            .processor-note {
                border-radius: 18px;
                background: rgba(15, 23, 42, .06);
                color: #475569;
                padding: 12px 14px;
                font-size: .86rem;
                margin-bottom: 14px;
            }
            .insight-card {
                border-radius: 26px;
                padding: 22px;
                background: linear-gradient(135deg, rgba(15,23,42,.96), rgba(30,41,59,.92));
                color: white;
                box-shadow: 0 22px 55px rgba(15, 23, 42, .18);
                margin: 18px 0;
            }
            .insight-card h3 {
                color: white;
                margin: 0 0 8px;
            }
            .insight-card p, .insight-card li {
                color: #dbeafe;
            }
            .insight-meta {
                color: #fdba74;
                font-size: .82rem;
                font-weight: 900;
                text-transform: uppercase;
                letter-spacing: .08em;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_hero() -> None:
    st.markdown(
        """
        <section class="body-lab-hero">
            <span class="coach-pill">Body progress lab</span>
            <h1>Track visible progress without making the coach guess.</h1>
            <p>
                Upload consistent front, side, back, or running-form photos. Today this stores a private visual timeline
                and avatar state. Later, the same module can plug into SAM 3D Body for mesh and pose outputs.
            </p>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _latest_sam_avatar(scans_df: pd.DataFrame):
    if scans_df.empty:
        return None, {}, {}
    recent = scans_df.sort_values(["scan_date", "created_at"], ascending=False)
    for row in recent.itertuples():
        measurements = _scan_measurements(row)
        shape_metrics = measurements.get("shape_metrics") or {}
        processor = str(getattr(row, "processor_name", "") or measurements.get("processor", ""))
        if shape_metrics and ("sam3d" in processor or getattr(row, "mesh_path", None)):
            return row, measurements, shape_metrics
    return None, {}, {}


def _scale_from_ratio(value: object, baseline: float, min_value: float = 0.75, max_value: float = 1.35) -> float:
    try:
        scale = float(value) / baseline
    except (TypeError, ValueError, ZeroDivisionError):
        return 1.0
    return max(min_value, min(max_value, scale))


def _render_sam_avatar(snapshot: dict, scans, scans_df: pd.DataFrame) -> bool:
    avatar = build_avatar_state(snapshot, scans)
    row, measurements, shape = _latest_sam_avatar(scans_df)
    if row is None:
        return False

    latest = pd.Timestamp(row.scan_date).date().isoformat()
    width_scale = _scale_from_ratio(shape.get("sam3d_width_to_height_ratio"), 0.52)
    depth_scale = _scale_from_ratio(shape.get("sam3d_depth_to_height_ratio"), 0.38, 0.7, 1.45)
    preview_path = getattr(row, "preview_image_path", None)
    metrics_html = _shape_metrics_html(measurements)
    view = str(getattr(row, "view", "scan")).replace("_", " ").title()

    st.markdown(
        f"""
        <div class="sam-avatar-card" style="--sam-avatar-color:{avatar.color}; --sam-width-scale:{width_scale:.3f}; --sam-depth-scale:{depth_scale:.3f};">
            <div class="sam-avatar-topline">SAM 3D avatar · {escape(view)} · {latest}</div>
            <div class="sam-avatar-title">Mesh-Based Runner Avatar</div>
            <div class="sam-avatar-subtitle">
                Shape is driven by your latest SAM mesh proportions. Use it for relative progress tracking, not diagnosis.
            </div>
            <div class="avatar-chip-row">
                <div class="avatar-chip">{escape(avatar.readiness_label)}</div>
                <div class="avatar-chip">{escape(avatar.load_label)}</div>
                <div class="avatar-chip">{escape(avatar.recovery_label)}</div>
                <div class="avatar-chip">{avatar.body_scan_count} scans · latest {latest}</div>
            </div>
            {metrics_html}
            <div class="sam-avatar-mesh-note">Mesh is stored locally and used only for relative shape tracking.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if preview_path and Path(preview_path).exists():
        st.image(preview_path, caption="Latest SAM 3D preview", width="stretch")
    return True


def _render_avatar(snapshot: dict, scans, scans_df: pd.DataFrame | None = None) -> None:
    if scans_df is not None and _render_sam_avatar(snapshot, scans, scans_df):
        return

    avatar = build_avatar_state(snapshot, scans)
    latest = avatar.latest_scan_date.isoformat() if avatar.latest_scan_date else "No scan yet"
    st.markdown(
        f"""
        <div class="avatar-card" style="--avatar-color:{avatar.color};">
            <div class="avatar-figure">
                <div class="avatar-head"></div>
                <div class="avatar-torso"></div>
                <div class="avatar-arm left"></div>
                <div class="avatar-arm right"></div>
                <div class="avatar-leg left"></div>
                <div class="avatar-leg right"></div>
            </div>
            <div class="avatar-title">{escape(avatar.title)}</div>
            <div class="avatar-subtitle">{escape(avatar.subtitle)}</div>
            <div class="avatar-chip-row">
                <div class="avatar-chip">{escape(avatar.readiness_label)}</div>
                <div class="avatar-chip">{escape(avatar.load_label)}</div>
                <div class="avatar-chip">{escape(avatar.recovery_label)}</div>
                <div class="avatar-chip">{avatar.body_scan_count} scans · latest {latest}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _timeline_chart(scans_df: pd.DataFrame) -> go.Figure:
    figure = go.Figure()
    if scans_df.empty:
        figure.add_annotation(
            text="Upload your first body progress photo to start the timeline.",
            x=0.5,
            y=0.5,
            xref="paper",
            yref="paper",
            showarrow=False,
        )
    else:
        counts = scans_df.groupby([scans_df["scan_date"].dt.date, "view"]).size().reset_index(name="count")
        figure.add_trace(
            go.Scatter(
                x=counts["scan_date"],
                y=counts["view"],
                mode="markers",
                marker=dict(
                    size=counts["count"] * 10 + 16,
                    color=counts["count"],
                    colorscale=[[0, "#fed7aa"], [1, "#fc4c02"]],
                    line=dict(color="white", width=2),
                    showscale=True,
                    colorbar=dict(title="scans"),
                ),
                customdata=counts[["count"]],
                hovertemplate="%{x}<br>%{y}<br>%{customdata[0]} scan(s)<extra></extra>",
            )
        )
    figure.update_layout(
        title="Body Progress Timeline",
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,.45)",
        margin=dict(l=28, r=22, t=58, b=32),
        font=dict(family="Manrope, sans-serif", color="#111827"),
        height=330,
    )
    figure.update_xaxes(title="Date", gridcolor="rgba(100,116,139,.14)")
    figure.update_yaxes(title="View", gridcolor="rgba(100,116,139,.14)")
    return figure


def _render_scan_grid(scans_df: pd.DataFrame) -> None:
    if scans_df.empty:
        st.info("No body progress scans yet.")
        return

    recent = scans_df.sort_values("scan_date", ascending=False).head(6)
    columns = st.columns(3)
    for index, row in enumerate(recent.itertuples()):
        with columns[index % 3]:
            path = row.preview_image_path or row.source_image_path
            if path and Path(path).exists():
                st.image(path, width="stretch")
            metrics = _scan_metrics_html(row)
            st.markdown(
                f"""
                <div class="scan-card-copy">
                    <span>{escape(str(row.view).replace("_", " ").title())} · {escape(str(row.status))}</span>
                    <strong>{pd.Timestamp(row.scan_date).date()}</strong>
                    <p class="coach-muted">{escape(str(row.notes or "No notes"))}</p>
                    {metrics}
                </div>
                """,
                unsafe_allow_html=True,
            )


def _scan_measurements(row) -> dict:
    raw = getattr(row, "measurements_json", None)
    if not raw or pd.isna(raw):
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}


def _metric_chip(label: str, value: object, suffix: str = "") -> str:
    if value is None or value == "":
        return ""
    return f'<span class="metric-chip">{escape(label)} {escape(str(value))}{escape(suffix)}</span>'


def _format_metric_value(value: object, digits: int = 3) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.{digits}f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def _shape_metric_tile(label: str, value: object, digits: int = 3) -> str:
    formatted = _format_metric_value(value, digits)
    if not formatted:
        return ""
    return (
        '<div class="shape-metric">'
        f"<small>{escape(label)}</small>"
        f"<strong>{escape(formatted)}</strong>"
        "</div>"
    )


def _shape_metrics_html(measurements: dict) -> str:
    shape = measurements.get("shape_metrics") or {}
    if not isinstance(shape, dict):
        return ""
    tiles = [
        _shape_metric_tile("Height proxy", shape.get("sam3d_height_proxy")),
        _shape_metric_tile("Width proxy", shape.get("sam3d_width_proxy")),
        _shape_metric_tile("Depth proxy", shape.get("sam3d_depth_proxy")),
        _shape_metric_tile("W/H ratio", shape.get("sam3d_width_to_height_ratio")),
        _shape_metric_tile("D/H ratio", shape.get("sam3d_depth_to_height_ratio")),
        _shape_metric_tile("W/D ratio", shape.get("sam3d_width_to_depth_ratio")),
        _shape_metric_tile("L/R balance", shape.get("sam3d_left_right_vertex_balance")),
        _shape_metric_tile("F/B balance", shape.get("sam3d_front_back_vertex_balance")),
        _shape_metric_tile("Vertices", shape.get("sam3d_vertex_count"), 0),
        _shape_metric_tile("Faces", shape.get("sam3d_face_count"), 0),
        _shape_metric_tile("Shoulder px", shape.get("sam3d_keypoint_shoulder_width_px"), 1),
        _shape_metric_tile("Hip px", shape.get("sam3d_keypoint_hip_width_px"), 1),
    ]
    tiles = [tile for tile in tiles if tile]
    if not tiles:
        return ""
    return (
        '<div class="shape-metric-panel">'
        '<div class="shape-metric-title">SAM 3D shape metrics</div>'
        f'<div class="shape-metric-grid">{"".join(tiles)}</div>'
        "</div>"
    )


def _scan_metrics_html(row) -> str:
    measurements = _scan_measurements(row)
    chips = [
        _metric_chip("quality", measurements.get("pose_quality")),
        _metric_chip("shoulder", measurements.get("shoulder_tilt_degrees"), "°"),
        _metric_chip("hip", measurements.get("hip_tilt_degrees"), "°"),
        _metric_chip("lean", measurements.get("torso_lean_degrees"), "°"),
        _metric_chip("L knee", measurements.get("left_knee_angle_degrees"), "°"),
        _metric_chip("R knee", measurements.get("right_knee_angle_degrees"), "°"),
    ]
    chips = [chip for chip in chips if chip]
    if not chips:
        message = measurements.get("message") or measurements.get("setup")
        if not message:
            return _shape_metrics_html(measurements)
        chips = [f'<span class="metric-chip">{escape(str(message))}</span>']
    return f'<div class="metric-chip-row">{"".join(chips)}</div>{_shape_metrics_html(measurements)}'


def _render_insight_payload(payload: dict, title: str = "Latest Scan Insight") -> None:
    st.markdown(
        f"""
        <div class="insight-card">
            <div class="insight-meta">{escape(title)} · {int(float(payload.get("confidence", 0) or 0))}% confidence</div>
            <h3>{escape(str(payload.get("summary", "No summary available.")))}</h3>
        </div>
        """,
        unsafe_allow_html=True,
    )
    columns = st.columns(2)
    sections = [
        ("Visual Changes", payload.get("visual_changes", [])),
        ("Posture and Symmetry", payload.get("posture_and_symmetry", [])),
        ("Running Form Meaning", payload.get("running_form_implications", [])),
        ("Progress Trends", payload.get("progress_trends", [])),
        ("Coaching Actions", payload.get("coaching_actions", [])),
        ("Next Photo Protocol", payload.get("next_photo_protocol", [])),
        ("Evidence", payload.get("evidence", [])),
        ("Limitations", payload.get("limitations", [])),
    ]
    for index, (section_title, items) in enumerate(sections):
        with columns[index % 2]:
            cleaned = [str(item).strip() for item in (items or []) if str(item).strip()]
            if cleaned:
                st.markdown(f"**{section_title}**")
                for item in cleaned:
                    st.markdown(f"- {item}")


def _latest_insight_payload(insights_df: pd.DataFrame) -> dict | None:
    if insights_df.empty:
        return None
    raw = insights_df.iloc[0]["payload_json"]
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {"summary": insights_df.iloc[0]["summary"]}


st.set_page_config(page_title="Body Progress", page_icon="B", layout="wide")
apply_dashboard_theme()
_body_progress_css()

settings = get_settings()
if not settings.use_sam:
    st.warning("Body Progress is disabled. Set use_sam=true in .env and restart Streamlit to enable it.")
    st.stop()

bundle = load_training_bundle()
settings_col, avatar_col = st.columns([1.2, 0.8])
with session_scope() as session:
    scans_df = _body_scans_dataframe(session, bundle.user.id)
    scans = _body_scan_summaries(scans_df)
    insights_df = _body_scan_insights_dataframe(session, bundle.user.id)

_render_hero()

with settings_col:
    st.subheader("Add Progress Scan")
    st.markdown(
        f"""
        <div class="processor-note">
            Active body processor: <strong>{escape(settings.body_scan_processor)}</strong>.
            Use <strong>sam3d</strong> for Meta SAM 3D Body rendered previews, <strong>mediapipe</strong> for fast
            local pose metrics, or <strong>multihmr</strong> for the external mesh adapter hook.
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.form("body_progress_upload"):
        uploaded = st.file_uploader("Progress photo", type=["jpg", "jpeg", "png", "webp"])
        scan_date = st.date_input("Scan date", value=date.today())
        view_label = st.selectbox("View", options=list(VIEW_OPTIONS.keys()))
        notes = st.text_area(
            "Notes",
            placeholder="Example: morning check-in, post long-run, race photo, posture snapshot.",
        )
        consent = st.checkbox("Store this image locally for my private timeline", value=True)
        submitted = st.form_submit_button("Save body scan")

    if submitted:
        if uploaded is None:
            st.error("Upload a photo before saving.")
        else:
            service = BodyProgressService()
            with session_scope() as session:
                result = service.upload_scan(
                    session=session,
                    user_id=bundle.user.id,
                    scan_date=scan_date,
                    view=VIEW_OPTIONS[view_label],
                    upload=uploaded,
                    filename=uploaded.name,
                    content_type=uploaded.type,
                    notes=notes,
                    consent_to_store_image=consent,
                )
            st.success(f"Stored body scan #{result.scan_id}. Processor status: {result.status}.")
            st.rerun()

with avatar_col:
    _render_avatar(bundle.snapshot, scans, scans_df)

st.plotly_chart(_timeline_chart(scans_df), width="stretch")

st.subheader("Recent Scans")
_render_scan_grid(scans_df)

st.subheader("LLM Scan Understanding")
latest_insight = _latest_insight_payload(insights_df)
with st.form("body_scan_insight_form"):
    athlete_question = st.text_area(
        "What do you want the coach to focus on?",
        placeholder="Example: compare my latest side scan with previous scans and tell me what it means for running form.",
    )
    generate_insight = st.form_submit_button("Analyze my scans with LLM")

if generate_insight:
    if scans_df.empty:
        st.error("Upload at least one body scan before generating an insight.")
    else:
        with st.spinner("Analyzing scan history and previous insights..."):
            service = BodyScanInsightService()
            with session_scope() as session:
                insight = service.generate(session, bundle.user, athlete_question=athlete_question)
        st.success(f"Stored body scan insight #{insight.insight_id}.")
        _render_insight_payload(insight.payload, "Fresh Scan Insight")
elif latest_insight:
    _render_insight_payload(latest_insight)
    with st.expander("Previous scan insight history"):
        for row in insights_df.head(6).itertuples():
            st.markdown(f"**{pd.Timestamp(row.insight_date).date()}** · {escape(str(row.model_provider or 'llm'))}")
            st.write(row.summary)
else:
    st.info("No LLM scan insights yet. Generate one after uploading scans.")

with st.expander("3D body model integration plan"):
    st.markdown(
        """
        This page now runs a lightweight local pose processor by default and stays ready for heavier 3D models.

        - `BODY_SCAN_PROCESSOR=sam3d` runs Meta SAM 3D Body and stores the rendered 3D preview.
        - `BODY_SCAN_PROCESSOR=mediapipe` extracts pose landmarks, annotated previews, and posture metrics from photos.
        - `BODY_SCAN_PROCESSOR=multihmr` switches to the external Multi-HMR adapter hook.
        - Store mesh files, rendered previews, keypoints, and pose/shape summaries in the existing scan output fields.
        - Keep raw photos private and deletable; send only summarized body/form context to the coach.
        - Do not use scan outputs for medical diagnosis or exact body composition claims.
        """
    )
