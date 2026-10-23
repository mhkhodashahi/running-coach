"""Athlete-owned week and individually approved coach proposals."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import streamlit as st

from coach.plan import interpret_revision
from coach.planning import propose_week
from coach.proposals import (
    apply,
    dismiss,
    get_week,
    list_commitments,
    list_proposals,
    manual_session,
    monday,
    request_revision,
    save_commitment,
    undo_last,
)
from config import get_settings
from ui.sidebar import render_sidebar_menu

render_sidebar_menu()
settings = get_settings()
user_id = settings.default_user_id
today = datetime.now(ZoneInfo(settings.local_timezone)).date()
st.title("Plan")
start = monday(st.date_input("Week of", value=monday(today)))

st.subheader("Fixed team commitments")
commitments = list_commitments(settings.db_path, user_id)
for commitment in commitments:
    columns = st.columns([3, 1])
    columns[0].write(f"{('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')[commitment['weekday']]} "
                     f"{commitment['start_time']} · {commitment['sport']} {commitment['kind']} · "
                     f"{commitment['typical_duration_min']} min")
    active = columns[1].toggle("Active", value=bool(commitment["active"]), key=f"fixed_{commitment['id']}")
    if active != bool(commitment["active"]):
        save_commitment(settings.db_path, user_id, weekday=commitment["weekday"],
                        start_time=commitment["start_time"], sport=commitment["sport"],
                        kind=commitment["kind"], duration_min=commitment["typical_duration_min"],
                        active=active, commitment_id=commitment["id"])
        st.rerun()
with st.form("add_fixed"):
    weekday = st.selectbox("Day", range(7), format_func=lambda n: ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[n])
    time = st.time_input("Start", value=datetime.strptime("19:00", "%H:%M").time())
    sport = st.selectbox("Team sport", ("volleyball", "football"))
    kind = st.selectbox("Kind", ("training", "match"))
    duration = st.number_input("Typical duration (min)", min_value=15, max_value=300, value=90, step=5)
    add_fixed = st.form_submit_button("Add commitment")
if add_fixed:
    try:
        save_commitment(settings.db_path, user_id, weekday=weekday, start_time=time.strftime("%H:%M"),
                        sport=sport, kind=kind, duration_min=int(duration))
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))

st.subheader("This week")
week = get_week(settings.db_path, user_id, start)
for offset in range(7):
    day = start + timedelta(days=offset)
    items = [item for item in week["sessions"] if item["date"] == day.isoformat()]
    text = "; ".join(f"{item['sport'].title()} · {item['intent']} · {item['duration_min']} min"
                     f"{' · fixed' if item['origin'] == 'fixed' else ''}"
                     f"{' · done' if item['status'] == 'done' else ''}" for item in items) or "Open"
    st.write(f"**{day:%a %d %b}**  {text}")

with st.expander("Edit a session by hand"):
    with st.form("manual_session"):
        selected = st.selectbox("Session", [None, *[item["id"] for item in week["sessions"]
                                             if item["id"] and item["origin"] != "fixed" and item["status"] == "planned"]],
                                format_func=lambda identifier: "New session" if identifier is None else
                                next(f"{item['date']} {item['sport']}" for item in week["sessions"]
                                     if item["id"] == identifier))
        day = st.date_input("Date", value=start, min_value=start, max_value=start + timedelta(days=6))
        sport = st.selectbox("Sport", ("running", "gym", "football", "volleyball"))
        intent = st.selectbox("Intent", ("easy", "recovery", "steady", "tempo", "race", "light", "skills only"))
        minutes = st.number_input("Duration (min)", min_value=15, max_value=300, value=45)
        cap = st.number_input("HR cap (optional)", min_value=0, max_value=240, value=0)
        notes = st.text_input("Notes", max_chars=500)
        save_manual = st.form_submit_button("Save session")
    if save_manual:
        try:
            manual_session(settings.db_path, user_id, {"date": day.isoformat(), "sport": sport,
                           "intent": intent, "duration_min": int(minutes),
                           "hr_cap_bpm": int(cap) or None, "notes": notes or None}, session_id=selected)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

actions = st.columns(2)
if actions[0].button("Suggest week", icon=":material/auto_awesome:"):
    try:
        proposal = propose_week(start, settings=settings, today=today)
        st.success(f"Proposal {proposal['id']} created. Review each change below.")
        st.rerun()
    except (ValueError, RuntimeError, PermissionError) as exc:
        st.error(str(exc))
if actions[1].button("Undo last coach changes", icon=":material/undo:"):
    try:
        undo_last(settings.db_path, user_id)
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))

st.subheader("Proposals")
for proposal in list_proposals(settings.db_path, user_id, start):
    with st.expander(f"{proposal['summary']} · {proposal['status']} · {proposal['created_at'][:10]}"):
        evidence = {fact["id"]: fact["display"] for fact in proposal["facts"]}
        chosen = []
        for change in proposal["changes"]:
            item = change["session"]
            label = f"{item['date']} · {change['change_type']} {item['sport']} {item['intent']} · {item['duration_min']} min"
            if proposal["status"] == "pending":
                if st.checkbox(label, value=True, key=f"proposal_{proposal['id']}_{change['id']}"):
                    chosen.append(change["id"])
            else:
                st.write(f"{label} · {change['decision']}")
            st.caption(change["reason"] + " · " + "; ".join(evidence.get(key, key) for key in change["fact_ids"]))
        if proposal["status"] == "pending":
            buttons = st.columns(3)
            if buttons[0].button(f"Apply {len(chosen)} changes", key=f"apply_{proposal['id']}",
                                 disabled=not chosen):
                try:
                    apply(settings.db_path, user_id, proposal["id"], chosen)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
            if buttons[1].button("Apply nothing", key=f"none_{proposal['id']}"):
                apply(settings.db_path, user_id, proposal["id"], [])
                st.rerun()
            if buttons[2].button("Dismiss", key=f"dismiss_{proposal['id']}"):
                dismiss(settings.db_path, user_id, proposal["id"])
                st.rerun()
            with st.form(f"revision_{proposal['id']}"):
                request = st.text_input("Request revision", key=f"revision_text_{proposal['id']}",
                                        placeholder="Make Saturday a rest day")
                revise = st.form_submit_button("Request revision")
            if revise:
                try:
                    day, session = interpret_revision(request, start, None)
                    matching = next((item for item in week["sessions"] if item["date"] == day.isoformat()
                                     and item["origin"] != "fixed"), None)
                    if session is None and matching is None:
                        raise ValueError("No non-fixed session to remove on that day")
                    item = ({**matching} if session is None else
                            {"date": day.isoformat(), **session, "notes": None, "id": matching["id"] if matching else None})
                    replacement = [{"change_type": "remove" if session is None else "modify" if matching else "add",
                                    "session": item, "reason": "You asked for this change.",
                                    "fact_ids": [proposal["facts"][0]["id"]]}]
                    request_revision(settings.db_path, user_id, proposal["id"], request, replacement)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
