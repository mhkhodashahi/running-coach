from __future__ import annotations

from pathlib import Path


def test_streamlit_navigation_no_longer_includes_performance_dashboard() -> None:
    main_source = Path("app/main.py").read_text()
    connect_plus_source = Path("app/pages/10_Connect_Plus.py").read_text()

    assert "Performance Dashboard" not in main_source
    assert "pages/6_Analysis.py" not in main_source
    assert "Performance Dashboard" not in connect_plus_source
    assert not Path("app/pages/6_Analysis.py").exists()
    assert not Path("app/performance_dashboard.html").exists()
