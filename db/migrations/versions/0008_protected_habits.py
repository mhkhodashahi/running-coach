"""Add athlete-owned recurring protected habits without seeding or rewriting plans."""

import sqlalchemy as sa
from alembic import op

revision = "0008_protected_habits"
down_revision = "0007_proposal_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "protected_habits" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "protected_habits",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("sport", sa.String(16), nullable=False),
        sa.Column("intent", sa.String(32), nullable=False),
        sa.Column("duration_min", sa.Integer(), nullable=False),
        sa.Column("per_week", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.CheckConstraint("sport IN ('running','gym','football','volleyball')", name="ck_protected_habits_sport"),
        sa.CheckConstraint("duration_min BETWEEN 15 AND 300", name="ck_protected_habits_duration"),
        sa.CheckConstraint("per_week BETWEEN 1 AND 7", name="ck_protected_habits_frequency"),
    )
    op.create_index("ix_protected_habits_user_id", "protected_habits", ["user_id"])


def downgrade() -> None:
    raise RuntimeError("Protected habits must not be discarded; restore the backup.")
