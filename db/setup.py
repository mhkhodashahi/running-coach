"""Read-only database readiness check for application startup."""

import shlex
import sqlite3
from contextlib import closing
from pathlib import Path

from alembic.script import ScriptDirectory

from db.migration_runner import migration_config
from db.session import engine


def init_db() -> None:
    """Require migration head without creating a database or changing its schema."""
    if engine.url.get_backend_name() != "sqlite" or not engine.url.database or engine.url.database == ":memory:":
        raise ValueError("Application initialization requires a file-backed SQLite database.")
    database = Path(engine.url.database).expanduser().resolve()
    message = (
        "Database needs an upgrade. Stop all jobs, then run:\n"
        f"python -m scripts.upgrade_db --db {shlex.quote(str(database))}"
    )
    if not database.is_file():
        raise RuntimeError(message)
    head = ScriptDirectory.from_config(migration_config()).get_current_head()
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        version_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        ).fetchone()
        versions = connection.execute("SELECT version_num FROM alembic_version").fetchall() if version_table else []
    if versions != [(head,)]:
        raise RuntimeError(message)
