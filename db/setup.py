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
    _migrate_activities_table()
    _migrate_activity_coaching_insights_table()
    _create_prediction_snapshots_table()


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


def _migrate_activities_table() -> None:
    inspector = inspect(engine)
    if "activities" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("activities")}
    migrations = {
        "activity_name": "ALTER TABLE activities ADD COLUMN activity_name VARCHAR(160)",
    }
    with engine.begin() as connection:
        for column_name, statement in migrations.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))


def _migrate_activity_coaching_insights_table() -> None:
    inspector = inspect(engine)
    if "activity_coaching_insights" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("activity_coaching_insights")}
    migrations = {
        "updated_at": "ALTER TABLE activity_coaching_insights ADD COLUMN updated_at DATETIME",
    }
    with engine.begin() as connection:
        for column_name, statement in migrations.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))


def _create_prediction_snapshots_table() -> None:
    inspector = inspect(engine)
    if "prediction_snapshots" in inspector.get_table_names():
        return

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS prediction_snapshots (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    activity_id INTEGER,
                    goal_id INTEGER,
                    prediction_date DATE NOT NULL,
                    race_distance_km FLOAT NOT NULL,
                    predicted_time_minutes FLOAT NOT NULL,
                    predicted_pace FLOAT NOT NULL,
                    gap_minutes FLOAT NOT NULL,
                    confidence FLOAT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    CONSTRAINT uq_prediction_snapshots_activity_goal UNIQUE (activity_id, goal_id),
                    FOREIGN KEY(user_id) REFERENCES users (id),
                    FOREIGN KEY(activity_id) REFERENCES activities (id),
                    FOREIGN KEY(goal_id) REFERENCES goals (id)
                )
                """
            )
        )
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_prediction_snapshots_user_id ON prediction_snapshots (user_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_prediction_snapshots_activity_id ON prediction_snapshots (activity_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_prediction_snapshots_goal_id ON prediction_snapshots (goal_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_prediction_snapshots_prediction_date ON prediction_snapshots (prediction_date)"))
