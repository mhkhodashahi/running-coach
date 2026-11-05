from pathlib import Path


def test_web_modules_delegate_persistence_to_repositories() -> None:
    root = Path(__file__).parents[1] / "web"
    forbidden = (
        "sqlite3.connect(",
        "create_engine(",
        "Session(",
        ".execute(",
        ".query(",
    )

    violations = {
        str(path.relative_to(root)): pattern
        for path in root.rglob("*.py")
        if path.name != "test_web_repository_boundary.py"
        for source in (path.read_text(encoding="utf-8"),)
        for pattern in forbidden
        if pattern in source
    }

    assert not violations
