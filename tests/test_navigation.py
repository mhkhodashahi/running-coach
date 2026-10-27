from __future__ import annotations

import ast
from pathlib import Path


def test_v2_navigation_keeps_all_routes_accessible() -> None:
    source = Path("web/templates/base.html").read_text()
    for destination in ("/", "/trends", "/plan", "/settings"):
        assert source.count(f'href="{destination}"') >= 2
    assert 'href="/coach"' in source
    assert 'href="/activities"' in Path("web/templates/trends.html").read_text()
    assert 'data-open-coach' in source
    assert 'aria-current="page"' in source
    assert "v2-secondary-link" not in source
    assert "icon('chat')" in source


def test_active_python_never_imports_retired_ui() -> None:
    for folder in ("web", "services", "coach", "metrics", "analytics", "db", "llm", "utils", "scripts", "tests"):
        for path in Path(folder).rglob("*.py"):
            tree = ast.parse(path.read_text())
            imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                        for alias in node.names]
            assert all(name and name.split(".")[0] not in {"app", "ui", "legacy"}
                       for name in imports), path
