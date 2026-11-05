from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
RUNTIME_PACKAGES = ("analytics", "coach", "llm", "metrics", "scripts", "services", "utils", "web", "worker")
FORBIDDEN = ("sqlite3.connect(", ".execute(", ".query(")
OPERATIONAL_EXCEPTIONS = {
    "scripts/backup_db.py",
    "scripts/restore_db.py",
    "worker/backup.py",
}


def test_runtime_sql_is_confined_to_repository_modules() -> None:
    violations = []
    for package in RUNTIME_PACKAGES:
        for path in (ROOT / package).rglob("*.py"):
            relative = path.relative_to(ROOT).as_posix()
            if relative in OPERATIONAL_EXCEPTIONS:
                continue
            source = path.read_text(encoding="utf-8")
            violations.extend(f"{relative}: {pattern}" for pattern in FORBIDDEN if pattern in source)

    assert not violations


def test_legacy_repository_path_only_forwards_to_canonical_package() -> None:
    source = (ROOT / "db/repository.py").read_text(encoding="utf-8")
    assert "from db.repositories import compatibility" in source
    assert not any(pattern in source for pattern in FORBIDDEN)
