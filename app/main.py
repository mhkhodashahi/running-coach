"""Streamlit navigation entry point."""

from __future__ import annotations

import streamlit as st

from config import get_settings

settings = get_settings()

pages = [
    st.Page("dashboard.py", title="Dashboard", icon=":material/dashboard:"),
    st.Page("pages/1_Activities.py", title="Activities", icon=":material/directions_run:"),
    st.Page("pages/2_Recovery.py", title="Recovery", icon=":material/monitor_heart:"),
    st.Page(
        "pages/3_Goal_Achievement_Readiness.py",
        title="Goal Achievement Readiness",
        icon=":material/flag:",
    ),
    st.Page("pages/4_AI_Coach.py", title="AI Coach", icon=":material/smart_toy:"),
    st.Page("pages/5_Goals_and_Digests.py", title="Goals and Digests", icon=":material/event_note:"),
    st.Page("pages/7_Quality_Sessions.py", title="Quality Sessions", icon=":material/fitness_center:"),
    st.Page("pages/8_Activity_Detail.py", title="Activity Detail", icon=":material/route:"),
    st.Page("pages/10_Connect_Plus.py", title="Connect+ Premium", icon=":material/diamond:"),
]

if settings.use_sam:
    pages.append(
        st.Page("pages/9_Body_Progress.py", title="Body Progress", icon=":material/accessibility_new:")
    )

navigation = st.navigation(pages)
navigation.run()
