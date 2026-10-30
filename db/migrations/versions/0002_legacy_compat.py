"""Apply the former setup.py compatibility updates once."""

from alembic import op
from sqlalchemy import inspect, text

from db.migrations.schema import baseline_metadata

revision = "0002_legacy_compat"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    # Preserve create_all's missing-table support, but never manage body-scan tables.
    metadata = baseline_metadata()
    tables = [table for table in metadata.sorted_tables if not table.name.startswith("body_scan")]
    metadata.create_all(connection, tables=tables)

    additions = {
        "users": {
            "name": "VARCHAR(80)",
            "training_days_per_week": "INTEGER",
            "injury_notes": "TEXT",
            "running_goal_time": "VARCHAR(16) NOT NULL DEFAULT '03:59:59'",
            "running_date": "DATE",
        },
        "activities": {"activity_name": "VARCHAR(160)"},
        "activity_coaching_insights": {"updated_at": "DATETIME"},
    }
    for table, columns in additions.items():
        existing = {column["name"] for column in inspect(connection).get_columns(table)}
        for column, definition in columns.items():
            if column not in existing:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
        if table == "users":
            for old, new in (("marathon_goal_time", "running_goal_time"), ("marathon_date", "running_date")):
                if old in existing:
                    connection.execute(text(f"UPDATE users SET {new} = {old} WHERE {new} IS NULL AND {old} IS NOT NULL"))

    connection.execute(text("""
        UPDATE goals SET name = 'Primary Running Goal'
        WHERE name = 'Primary Marathon Goal'
          AND goal_type = 'marathon_pb'
          AND notes = 'Default active goal created from app settings.'
    """))
    connection.execute(text("UPDATE goals SET goal_type = 'running_pb' WHERE goal_type = 'marathon_pb'"))


def downgrade() -> None:
    raise RuntimeError("Compatibility backfills cannot be reversed safely; restore the backup.")
