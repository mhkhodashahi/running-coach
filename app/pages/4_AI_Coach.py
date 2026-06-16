"""AI Coach page."""

from __future__ import annotations

import json

import streamlit as st

from config import get_settings
from db import repository
from db.session import session_scope
from services.coaching_workflow import CoachingWorkflowService
from services.training_context_service import load_training_bundle
from ui.components import render_coaching_card

st.title("AI Coach")

bundle = load_training_bundle()
settings = get_settings()
history = bundle.coaching_history.copy()

if not history.empty:
    latest = json.loads(history.iloc[0]["payload_json"])
    render_coaching_card(latest, "Latest Coaching Decision")
    with st.expander("Latest Telegram Preview"):
        st.write(latest.get("message_title", latest.get("email_subject", "n/a")))
        st.text(latest.get("message_body", latest.get("email_body", "n/a")))
else:
    st.info("No structured coaching decisions yet. Generate one below.")

st.subheader("Generate Coaching Digest")
st.caption(
    "This uses the active goal, recent Garmin data, deterministic checks, and the configured LLM provider."
)

with st.form("generate_coaching_form"):
    decision_type = st.selectbox("Digest type", options=["daily", "weekly"], index=0)
    athlete_note = st.text_area(
        "Optional athlete note",
        placeholder="Legs felt heavy after the long run, but heart rate stayed under control.",
    )
    can_message = bool(settings.telegram_bot_token and settings.telegram_chat_id)
    send_message = st.checkbox(
        "Send Telegram message after generating",
        value=False,
        help="Configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env first.",
        disabled=not can_message,
    )
    submit = st.form_submit_button("Generate digest")

if submit:
    workflow = CoachingWorkflowService()
    with st.spinner("Generating coaching digest..."):
        with session_scope() as session:
            user = repository.get_or_create_default_user(session, bundle.user.id)
            coaching = workflow.generate(
                session=session,
                user=user,
                decision_type=decision_type,
                athlete_note=athlete_note,
                send_message=send_message,
            )
    st.success("Coaching digest created.")
    if coaching.get("message_status") == "sent":
        st.success(coaching.get("message_status_message", "Telegram message sent."))
    elif coaching.get("message_status") == "failed":
        st.error(coaching.get("message_status_message", "Telegram send failed."))
    render_coaching_card(coaching, "Fresh Coaching Decision")
    with st.expander("Telegram Preview"):
        st.write(coaching.get("message_title", coaching.get("email_subject", "n/a")))
        st.text(coaching.get("message_body", coaching.get("email_body", "n/a")))
    st.rerun()

st.subheader("Decision History")
if history.empty:
    st.caption("History will appear after the first coaching digest is generated.")
else:
    for row in history.itertuples():
        coaching = json.loads(row.payload_json)
        with st.expander(f"{row.decision_date:%Y-%m-%d} | {row.decision_type} | {row.risk_level}"):
            render_coaching_card(coaching, "Decision")
