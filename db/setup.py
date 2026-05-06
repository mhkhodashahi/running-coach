"""Database initialization."""

from __future__ import annotations

from sqlalchemy import inspect, text

from config import get_settings
from db.models import Base
from db.session import engine


def init_db() -> None:
    """Create the SQLite database and all tables."""

    settings = get_settings()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _migrate_users_table()


def _migrate_users_table() -> None:
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("users")}
    migrations = {
        "name": "ALTER TABLE users ADD COLUMN name VARCHAR(80)",
        "training_days_per_week": "ALTER TABLE users ADD COLUMN training_days_per_week INTEGER",
        "injury_notes": "ALTER TABLE users ADD COLUMN injury_notes TEXT",
    }
    with engine.begin() as connection:
        for column_name, statement in migrations.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))
