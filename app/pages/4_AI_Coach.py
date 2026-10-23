"""Coach page."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import streamlit as st

from coach.plan import monday
from config import get_settings
from db import repository
from db.session import session_scope
from services.coaching_workflow import CoachingWorkflowService
from services.training_chat_service import TrainingChatService
from services.training_context_service import load_training_bundle
from services.weekly_plan_service import (
    accept_change,
    get_weekly_plan,
    list_proposals,
    propose_week,
    reject_change,
    revise_proposal,
    set_fixed_commitment,
    undo_last_coach_change,
)
from ui.components import render_coaching_card
from ui.sidebar import render_sidebar_menu

render_sidebar_menu()
st.title("Coach")

st.subheader("Ask the coach")
chat_service = TrainingChatService()
try:
    chat_history = chat_service.history()
except Exception:
    chat_history = []
for turn in chat_history:
    with st.chat_message("user"):
        st.write(turn["question"])
    with st.chat_message("assistant"):
        st.write(turn["answer"])
for index, suggestion in enumerate(st.session_state.get("coach_last_follow_ups", ())):
    if st.button(suggestion, key=f"coach_follow_up_{index}"):
        st.session_state["coach_follow_up"] = suggestion
        st.rerun()
chat_question = st.chat_input("Ask about training, recovery, or an activity")
follow_up = st.session_state.pop("coach_follow_up", None)
if chat_question or follow_up:
    with st.spinner("Checking your data..."):
        chat_reply = chat_service.answer(chat_question or follow_up)
    with st.chat_message("assistant"):
        st.write(chat_reply.text)
    st.session_state["coach_last_follow_ups"] = chat_reply.follow_ups
    if chat_reply.used_llm:
        st.rerun()

st.divider()

st.subheader("Weekly plan")
settings = get_settings()
today = datetime.now(ZoneInfo(settings.local_timezone)).date()
selected_day = st.date_input("Week of", value=monday(today), key="coach_plan_week")
week_start = monday(selected_day)
try:
    plan = get_weekly_plan(week_start, settings=settings)
    proposals = list_proposals(week_start, settings=settings)
except (ValueError, RuntimeError) as exc:
    st.error(str(exc))
    plan, proposals = None, []

if plan is not None:
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        session = plan["sessions"].get(day.isoformat())
        label = (f"{session['sport'].title()} | {session['intent']} | {session['duration_min']} min"
                 + (" | fixed" if session["fixed"] else "") if session else "Rest / open")
        st.write(f"**{day:%a %d %b}**  {label}")

    with st.form("team_commitment_form"):
        commitment_day = st.selectbox("Team training day", list(range(7)),
                                      format_func=lambda offset: (week_start + timedelta(days=offset)).strftime("%A"))
        commitment_sport = st.selectbox("Sport", ("football", "volleyball"))
        commitment_duration = st.number_input("Duration (min)", min_value=20, max_value=240, value=60, step=5)
        remove_commitment = st.checkbox("Remove this fixed commitment")
        save_commitment = st.form_submit_button("Update fixed team training")
    if save_commitment:
        try:
            set_fixed_commitment(week_start + timedelta(days=commitment_day),
                                 None if remove_commitment else commitment_sport,
                                 settings=settings, duration_min=int(commitment_duration))
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    if st.button("Suggest week", icon=":material/auto_awesome:"):
        try:
            propose_week(week_start, settings=settings, today=today)
            st.rerun()
        except ValueError as exc:
            st.info(str(exc))
    if st.button("Undo last coach change", icon=":material/undo:"):
        try:
            undo_last_coach_change(week_start, settings=settings)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    for proposal in proposals:
        with st.expander(f"Proposal {proposal['id']} | {proposal['status']} | {proposal['created_at'][:10]}"):
            evidence = {fact["id"]: fact["display"] for fact in proposal["facts"]}
            for change in proposal["changes"]:
                session = change["session"]
                title = (f"{change['day']}: {session['sport']} {session['intent']} "
                         f"({session['duration_min']} min)" if session else f"{change['day']}: rest")
                status = "accepted, then undone" if change["undone"] else change["status"]
                st.write(f"**{title}** | {status}")
                st.write(change["reason"])
                st.caption("Evidence: " + "; ".join(evidence[fact_id] for fact_id in change["fact_ids"]))
                if proposal["status"] == "open" and change["status"] == "pending":
                    left, right = st.columns(2)
                    if left.button("Accept", icon=":material/check:", key=f"accept_{change['id']}"):
                        try:
                            accept_change(change["id"], settings=settings)
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))
                    if right.button("Reject", icon=":material/close:", key=f"reject_{change['id']}"):
                        try:
                            reject_change(change["id"], settings=settings)
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))
            if proposal["status"] == "open":
                with st.form(f"revise_{proposal['id']}"):
                    revision_text = st.text_input("Ask for a revision", key=f"revision_{proposal['id']}",
                                                  placeholder="Make Saturday a rest day")
                    submit_revision = st.form_submit_button("Request revision")
                if submit_revision:
                    try:
                        revise_proposal(proposal["id"], revision_text, settings=settings)
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

st.divider()

bundle = load_training_bundle()
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
