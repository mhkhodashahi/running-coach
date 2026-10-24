"""Streamlit navigation entry point."""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from config import get_settings

settings = get_settings()


@dataclass(frozen=True)
class NavigationSpec:
    path: str
    title: str
    icon: str


def navigation_specs() -> list[NavigationSpec]:
    return [
        NavigationSpec("dashboard.py", title="Today", icon=":material/dashboard:"),
        NavigationSpec("pages/1_Activities.py", title="Training", icon=":material/monitoring:"),
        NavigationSpec("pages/2_Recovery.py", title="Health", icon=":material/monitor_heart:"),
        NavigationSpec(
            "pages/3_Goal_Achievement_Readiness.py",
            title="Goal",
            icon=":material/flag:",
        ),
        NavigationSpec("pages/4_AI_Coach.py", title="Coach", icon=":material/smart_toy:"),
        NavigationSpec("pages/6_Plan.py", title="Plan", icon=":material/calendar_month:"),
        NavigationSpec("pages/5_Goals_and_Digests.py", title="Goals", icon=":material/event_note:"),
        NavigationSpec("pages/7_Quality_Sessions.py", title="Key Sessions", icon=":material/fitness_center:"),
    ]


def build_pages() -> list[st.Page]:
    pages = [st.Page(spec.path, title=spec.title, icon=spec.icon) for spec in navigation_specs()]
    pages.append(
        st.Page(
            "pages/8_Activity_Detail.py",
            title="Activity Details",
            icon=":material/route:",
            visibility="hidden",
        )
    )
    return pages


def main() -> None:
    navigation = st.navigation(build_pages())
    navigation.run()


if __name__ == "__main__":
    main()
