"""Store the latest effort rating and one-time Telegram prompt state."""

import sqlalchemy as sa
from alembic import op

revision = "0010_activity_efforts"
down_revision = "0009_mobility_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "activity_efforts" not in tables:
        op.create_table(
        "activity_efforts",
        sa.Column("activity_id", sa.Integer(), sa.ForeignKey("activities.id"), primary_key=True),
        sa.Column("rpe", sa.Integer(), nullable=False),
        sa.Column("rated_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("note", sa.Text()),
        sa.CheckConstraint("rpe BETWEEN 0 AND 10", name="ck_activity_efforts_rpe"),
        sa.CheckConstraint("source IN ('web','telegram')", name="ck_activity_efforts_source"),
    )
    if "activity_effort_prompts" not in tables:
        op.create_table(
        "activity_effort_prompts",
        sa.Column("activity_id", sa.Integer(), sa.ForeignKey("activities.id"), primary_key=True),
        sa.Column("sent_at", sa.DateTime()),
        sa.Column("reminded_at", sa.DateTime()),
    )


def downgrade() -> None:
    raise RuntimeError("Effort ratings must not be discarded; restore the backup.")
