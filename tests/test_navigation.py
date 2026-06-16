from __future__ import annotations

from pathlib import Path


def test_default_navigation_pages_do_not_include_removed_surfaces() -> None:
    from app.main import navigation_specs

    page_paths = [spec.path for spec in navigation_specs()]

    assert page_paths == [
        "dashboard.py",
        "pages/1_Activities.py",
        "pages/2_Recovery.py",
        "pages/3_Goal_Achievement_Readiness.py",
        "pages/4_AI_Coach.py",
        "pages/5_Goals_and_Digests.py",
        "pages/7_Quality_Sessions.py",
        "pages/8_Activity_Detail.py",
    ]


def test_streamlit_navigation_excludes_removed_pages() -> None:
    main_source = Path("app/main.py").read_text()

    assert "Performance Dashboard" not in main_source
    assert "pages/6_Analysis.py" not in main_source
    assert not Path("app/pages/6_Analysis.py").exists()
    assert not Path("app/performance_dashboard.html").exists()
