"""Athlete-owned week and individually approved coach proposals."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import streamlit as st

from coach.planning import apply_draft, load_model, propose_week, revise_week, week_load_breakdown
from coach.proposals import (
    apply,
    dismiss,
    get_week,
    list_commitments,
    list_proposals,
    list_protected_habits,
    manual_session,
    monday,
    save_commitment,
    save_protected_habit,
    skip_manual_session,
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
if commitments:
    with st.expander("Edit commitment"):
        selected_fixed = st.selectbox(
            "Commitment", commitments,
            format_func=lambda item: f"{('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')[item['weekday']]} "
                                     f"{item['start_time']} {item['sport']}")
        with st.form("edit_fixed"):
            edit_day = st.selectbox("Day", range(7), index=selected_fixed["weekday"],
                                    format_func=lambda n: ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[n])
            edit_time = st.time_input("Start", value=datetime.strptime(selected_fixed["start_time"], "%H:%M").time())
            edit_sport = st.selectbox("Team sport", ("volleyball", "football"),
                                      index=("volleyball", "football").index(selected_fixed["sport"]))
            edit_kind = st.selectbox("Kind", ("training", "match"),
                                     index=("training", "match").index(selected_fixed["kind"]))
            edit_duration = st.number_input("Typical duration (min)", min_value=15, max_value=300,
                                            value=int(selected_fixed["typical_duration_min"]), step=5)
            edit_active = st.checkbox("Active", value=bool(selected_fixed["active"]))
            edit_submit = st.form_submit_button("Save commitment")
        if edit_submit:
            try:
                save_commitment(settings.db_path, user_id, weekday=edit_day,
                                start_time=edit_time.strftime("%H:%M"), sport=edit_sport, kind=edit_kind,
                                duration_min=int(edit_duration), active=edit_active,
                                commitment_id=selected_fixed["id"])
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

st.subheader("Protected habits")
protected = list_protected_habits(settings.db_path, user_id)
for habit in protected:
    columns = st.columns([3, 1])
    columns[0].write(f"{habit['sport'].title()} · {habit['intent']} · "
                     f"{habit['duration_min']} min · {habit['per_week']} per week")
    active = columns[1].toggle("Active", value=bool(habit["active"]), key=f"protected_{habit['id']}")
    if active != bool(habit["active"]):
        try:
            save_protected_habit(settings.db_path, user_id, sport=habit["sport"], intent=habit["intent"],
                                 duration_min=habit["duration_min"], per_week=habit["per_week"],
                                 active=active, habit_id=habit["id"])
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
with st.form("add_protected"):
    habit_sport = st.selectbox("Habit sport", ("gym", "running", "volleyball", "football"))
    habit_intent = st.selectbox("Habit intent", ("light upper body", "light", "easy", "recovery",
                                                 "steady", "tempo", "training", "match"))
    habit_duration = st.number_input("Habit duration (min)", min_value=15, max_value=300, value=30)
    habit_frequency = st.number_input("Times per week", min_value=1, max_value=7, value=2)
    add_habit = st.form_submit_button("Add protected habit")
if add_habit:
    try:
        save_protected_habit(settings.db_path, user_id, sport=habit_sport, intent=habit_intent,
                             duration_min=int(habit_duration), per_week=int(habit_frequency))
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))
if protected:
    with st.expander("Edit protected habit"):
        selected_habit = st.selectbox("Habit", protected,
                                      format_func=lambda item: f"{item['sport']} · {item['intent']} · {item['id']}")
        with st.form("edit_protected"):
            edit_habit_sport = st.selectbox("Sport", ("gym", "running", "volleyball", "football"),
                                            index=("gym", "running", "volleyball", "football").index(
                                                selected_habit["sport"]))
            edit_habit_intent = st.text_input("Intent", value=selected_habit["intent"], max_chars=32)
            edit_habit_duration = st.number_input("Duration (min)", min_value=15, max_value=300,
                                                   value=int(selected_habit["duration_min"]))
            edit_habit_frequency = st.number_input("Per week", min_value=1, max_value=7,
                                                    value=int(selected_habit["per_week"]))
            edit_habit_active = st.checkbox("Active", value=bool(selected_habit["active"]))
            edit_habit_submit = st.form_submit_button("Save habit")
        if edit_habit_submit:
            try:
                save_protected_habit(settings.db_path, user_id, sport=edit_habit_sport,
                                     intent=edit_habit_intent.strip(), duration_min=int(edit_habit_duration),
                                     per_week=int(edit_habit_frequency), active=edit_habit_active,
                                     habit_id=selected_habit["id"])
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

st.subheader("This week")
week = get_week(settings.db_path, user_id, start)
model = load_model(settings.db_path, user_id, start, settings)
breakdown = week_load_breakdown(week["sessions"], model, start)
for offset in range(7):
    day = start + timedelta(days=offset)
    items = [item for item in week["sessions"] if item["date"] == day.isoformat()]
    text = "; ".join(f"{item['sport'].title()} · "
                     f"{item['intent']} · {item['duration_min']} min"
                     f"{' · protected' if item['origin'] == 'protected' else ' · fixed' if item['origin'] == 'fixed' else ''}"
                     f"{' · done' if item['status'] == 'done' else ' · skipped' if item['status'] == 'skipped' else ''}"
                     for item in items) or "Open"
    load = breakdown["days"][offset]["estimated_load"]
    st.write(f"**{day:%a %d %b}**  {text} · {f'{load:.1f} TRIMP' if load is not None else 'Load unknown'}")
if breakdown["weekly_total"] is None:
    st.caption("Estimated week: load unknown")
elif breakdown["cap"] is None:
    st.caption(f"Estimated week: {breakdown['weekly_total']:.1f} TRIMP · not enough history for a load cap")
else:
    st.caption(f"Estimated week: {breakdown['weekly_total']:.1f} / {breakdown['cap']:.1f} TRIMP cap")
st.caption(f"Expected walking, not counted in training load: {breakdown['expected_walking_weekly']:.1f} TRIMP/week.")

with st.expander("Edit a session by hand"):
    with st.form("manual_session"):
        selected = st.selectbox("Session", [None, *[item["id"] for item in week["sessions"]
                                             if item["id"] and item["id"] > 0 and
                                             item["origin"] != "fixed" and item["status"] == "planned"]],
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
    if selected is not None and st.button("Skip selected session", key="skip_manual_session"):
        try:
            skip_manual_session(settings.db_path, user_id, selected)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

actions = st.columns(2)
if actions[0].button("Suggest week", icon=":material/auto_awesome:"):
    try:
        proposal = propose_week(start, settings=settings, today=today)
        if proposal["status"] in ("no_safe_change", "already_planned"):
            st.info(proposal["summary"] + " " + "; ".join(proposal["warnings"]))
        else:
            st.success(f"Proposal {proposal['id']} created. Review each group below.")
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
        groups = {}
        for change in proposal["changes"]:
            groups.setdefault(change["group_id"] or f"legacy-{change['id']}", []).append(change)
        for group_id, changes in groups.items():
            label = "; ".join(f"{change['session']['date']} · {change['change_type']} "
                              f"{change['session']['sport']} {change['session']['intent']} · "
                              f"{change['session']['duration_min']} min" for change in changes)
            if proposal["status"] == "pending":
                if st.checkbox(label, value=True, key=f"proposal_{proposal['id']}_{group_id}"):
                    chosen.extend(change["id"] for change in changes)
            else:
                st.write(f"{label} · {', '.join(change['decision'] for change in changes)}")
            for change in changes:
                st.caption(change["reason"] + " · " +
                           "; ".join(evidence.get(key, key) for key in change["fact_ids"]))
        try:
            preview = apply_draft(week["sessions"], [
                {"change_type": change["change_type"], "session": change["session"]}
                for change in proposal["changes"]])
            totals = week_load_breakdown(preview, model, start)
            st.caption("Proposed: " + "; ".join(
                f"{item['date']}: {item['estimated_load']:.1f} TRIMP"
                if item["estimated_load"] is not None else f"{item['date']}: unknown"
                for item in totals["days"]) +
                (f" · total {totals['weekly_total']:.1f} / {totals['cap']:.1f}"
                 if totals["weekly_total"] is not None and totals["cap"] is not None else
                 f" · total {totals['weekly_total']:.1f}, no load cap"
                 if totals["weekly_total"] is not None else " · total unknown"))
        except ValueError as exc:
            st.caption(f"Proposed load unavailable: {exc}")
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
                    revise_week(proposal["id"], request, settings=settings, today=today)
                    st.rerun()
                except (ValueError, RuntimeError, PermissionError) as exc:
                    st.error(str(exc))
