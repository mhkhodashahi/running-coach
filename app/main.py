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


def navigation_specs(use_sam: bool) -> list[NavigationSpec]:
    specs = [
        NavigationSpec("dashboard.py", title="Dashboard", icon=":material/dashboard:"),
        NavigationSpec("pages/1_Activities.py", title="Activities", icon=":material/directions_run:"),
        NavigationSpec("pages/2_Recovery.py", title="Recovery", icon=":material/monitor_heart:"),
        NavigationSpec(
            "pages/3_Goal_Achievement_Readiness.py",
            title="Goal Achievement Readiness",
            icon=":material/flag:",
        ),
        NavigationSpec("pages/4_AI_Coach.py", title="AI Coach", icon=":material/smart_toy:"),
        NavigationSpec("pages/5_Goals_and_Digests.py", title="Goals and Digests", icon=":material/event_note:"),
        NavigationSpec("pages/7_Quality_Sessions.py", title="Quality Sessions", icon=":material/fitness_center:"),
        NavigationSpec("pages/8_Activity_Detail.py", title="Activity Detail", icon=":material/route:"),
    ]

    if use_sam:
        specs.append(
            NavigationSpec("pages/9_Body_Progress.py", title="Body Progress", icon=":material/accessibility_new:")
        )

    return specs


def build_pages(use_sam: bool) -> list[st.Page]:
    return [st.Page(spec.path, title=spec.title, icon=spec.icon) for spec in navigation_specs(use_sam)]


def main() -> None:
    navigation = st.navigation(build_pages(settings.use_sam))
    navigation.run()


if __name__ == "__main__":
    main()
