"""V2 theme contrast and public message-link smoke checks."""

import re
import sqlite3
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from config import get_settings
from db.migration_runner import upgrade_database
from web.app import create_app

CSS_DIR = Path(__file__).resolve().parents[1] / "web" / "static" / "css"


def _luminance(hex_color: str) -> float:
    channels = [int(hex_color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
              for value in channels]
    return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722), strict=True))


def _contrast(left: str, right: str) -> float:
    a, b = sorted((_luminance(left), _luminance(right)))
    return (b + 0.05) / (a + 0.05)


def test_theme_tokens_meet_text_and_mark_contrast():
    css = (CSS_DIR / "v2.css").read_text()
    for match in re.finditer(r'(?::root, \[data-theme="night"\]|\[data-theme="day"\])\s*\{([^}]+)\}', css):
        tokens = dict(re.findall(r"--([\w-]+):\s*(#[0-9a-f]{6})", match.group(1)))
        for background in ("ground", "surface", "surface-raised"):
            for ink in ("ink", "ink-muted"):
                assert _contrast(tokens[ink], tokens[background]) >= 4.5, (background, ink)
            for mark in ("load", "sleep", "heart", *(f"zone-{index}" for index in range(1, 6))):
                assert _contrast(tokens[mark], tokens[background]) >= 3, (background, mark)
        assert _contrast(tokens["on-volt"], tokens["volt"]) >= 4.5
    assert '[data-theme="day"] .v2-recovery .v2-dial-progress{stroke:var(--volt-ink)}' in (
        CSS_DIR / "v2.css").read_text()


def test_only_v2_stylesheet_is_loaded_and_focus_styles_exist():
    base = (Path(__file__).resolve().parents[1] / "web/templates/base.html").read_text()
    assert "css/app.css" not in base
    assert base.count('rel="stylesheet"') == 1 and "css/v2.css" in base
    css = (CSS_DIR / "v2.css").read_text()
    assert ":focus-visible" in css and "prefers-reduced-motion" in css


def test_public_telegram_and_worker_paths_render(tmp_path):
    settings = replace(get_settings(), db_path=tmp_path / "public-links.db", llm_provider="none")
    upgrade_database(settings.db_path)
    with sqlite3.connect(settings.db_path) as connection:
        connection.execute("INSERT INTO users(id,max_hr,age,marathon_goal_time,running_goal_time) "
                           "VALUES(?,?,?,?,?)", (settings.default_user_id, 190, 30,
                           "04:00:00", "04:00:00"))
    with TestClient(create_app(settings, password="")) as client:
        for path in ("/", "/plan"):
            assert client.get(path).status_code == 200
