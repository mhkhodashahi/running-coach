from pathlib import Path


def test_worker_application_modules_delegate_sql_to_repositories() -> None:
    root = Path(__file__).parents[1] / "worker"
    modules = ("state.py", "jobs.py", "health.py", "memory.py")
    forbidden = ("sqlite3.connect(", ".execute(", ".query(", "create_engine(", "Session(")

    violations = {
        f"{module}: {pattern}"
        for module in modules
        for source in ((root / module).read_text(encoding="utf-8"),)
        for pattern in forbidden
        if pattern in source
    }

    assert not violations
