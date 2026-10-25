from __future__ import annotations

import ast
from pathlib import Path


def test_default_navigation_includes_settings_and_all_primary_pages() -> None:
    source = Path("web/templates/base.html").read_text()
    for destination in ("/", "/activities", "/trends", "/coach", "/plan", "/settings"):
        assert source.count(f'href="{destination}"') >= 2


def test_active_python_never_imports_retired_ui() -> None:
    for folder in ("web", "services", "coach", "metrics", "analytics", "db", "llm", "utils", "scripts", "tests"):
        for path in Path(folder).rglob("*.py"):
            tree = ast.parse(path.read_text())
            imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                        for alias in node.names]
            assert all(name and name.split(".")[0] not in {"app", "ui", "legacy"}
                       for name in imports), path
