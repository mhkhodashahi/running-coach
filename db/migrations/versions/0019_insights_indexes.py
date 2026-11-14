"""Index user/date reads and first-sample lookups without rewriting any rows."""

from alembic import op
from sqlalchemy import inspect

revision = "0019_insights_indexes"
down_revision = "0018_coach_memories"
branch_labels = None
depends_on = None

INDEXES = (
    ("ix_activities_user_date", "activities", ["user_id", "date"]),
    ("ix_activity_track_points_activity_timestamp", "activity_track_points", ["activity_id", "timestamp"]),
    ("ix_coaching_decisions_user_type_date", "coaching_decisions", ["user_id", "decision_type", "decision_date"]),
)


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    for name, table, columns in INDEXES:
        existing = {index["name"]: index["column_names"] for index in inspector.get_indexes(table)}
        if name in existing:
            if existing[name] != columns:
                raise RuntimeError(f"Index {name} already exists with different columns")
        else:
            op.create_index(name, table, columns)


def downgrade() -> None:
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
