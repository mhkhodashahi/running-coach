"""Add optional structured workouts to plans and proposals."""

import sqlalchemy as sa
from alembic import op

revision = "0017_detailed_workouts"
down_revision = "0016_morning_briefs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table in ("plan_sessions", "proposal_changes"):
        existing = {column["name"] for column in inspector.get_columns(table)}
        if "workout_type" not in existing:
            op.add_column(table, sa.Column("workout_type", sa.String(32), nullable=True))
        if "workout_json" not in existing:
            op.add_column(table, sa.Column("workout_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("proposal_changes", "workout_json")
    op.drop_column("proposal_changes", "workout_type")
    op.drop_column("plan_sessions", "workout_json")
    op.drop_column("plan_sessions", "workout_type")
