from pathlib import Path


def test_service_persistence_uses_repositories_not_direct_sql() -> None:
    root = Path(__file__).parents[1] / "services"
    modules = (
        "daily_decision_service.py",
        "morning_brief.py",
        "coach_memory_service.py",
        "timeline_notes.py",
        "training_chat_service.py",
        "effort_service.py",
        "weekly_plan_service.py",
        "import_service.py",
        "activity_coaching_service.py",
    )
    forbidden = ("sqlite3.connect(", "session.execute(", "session.query(", "db.execute(")

    for module in modules:
        source = (root / module).read_text(encoding="utf-8")
        assert not [pattern for pattern in forbidden if pattern in source], module
