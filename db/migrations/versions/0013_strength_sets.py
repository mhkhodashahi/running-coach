"""Store Garmin strength sets without changing existing activities."""

import sqlalchemy as sa
from alembic import op

revision = "0013_strength_sets"
down_revision = "0012_openai_usage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "activity_exercise_sets" not in inspector.get_table_names():
        op.create_table(
            "activity_exercise_sets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("activity_id", sa.Integer(), sa.ForeignKey("activities.id"), nullable=False),
            sa.Column("set_index", sa.Integer(), nullable=False),
            sa.Column("set_type", sa.String(16), nullable=False),
            sa.Column("start_time", sa.DateTime()),
            sa.Column("duration_seconds", sa.Float()),
            sa.Column("repetition_count", sa.Integer()),
            sa.Column("weight_grams", sa.Float()),
            sa.Column("exercises_json", sa.Text(), nullable=False, server_default="[]"),
            sa.UniqueConstraint("activity_id", "set_index", name="uq_activity_exercise_sets_index"),
        )
    if "ix_activity_exercise_sets_activity_id" not in {
        index["name"] for index in sa.inspect(op.get_bind()).get_indexes("activity_exercise_sets")
    }:
        op.create_index("ix_activity_exercise_sets_activity_id", "activity_exercise_sets", ["activity_id"])


def downgrade() -> None:
    raise RuntimeError("Strength sets must not be discarded; restore the backup.")
