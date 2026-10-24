"""Store non-training mobility plans without rebuilding plan_sessions."""

import sqlalchemy as sa
from alembic import op

revision = "0009_mobility_sessions"
down_revision = "0008_protected_habits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "plan_mobility_sessions" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "plan_mobility_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("sport", sa.String(16), nullable=False),
        sa.Column("intent", sa.String(32), nullable=False),
        sa.Column("duration_min", sa.Integer(), nullable=False),
        sa.Column("hr_cap_bpm", sa.Integer()),
        sa.Column("notes", sa.Text()),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("sport = 'mobility'", name="ck_plan_mobility_sport"),
        sa.CheckConstraint("intent = 'recovery'", name="ck_plan_mobility_intent"),
        sa.CheckConstraint("duration_min BETWEEN 15 AND 20", name="ck_plan_mobility_duration"),
        sa.CheckConstraint("hr_cap_bpm IS NULL", name="ck_plan_mobility_no_hr_cap"),
        sa.CheckConstraint("status IN ('planned','skipped')", name="ck_plan_mobility_status"),
    )
    op.create_index("ix_plan_mobility_user_date", "plan_mobility_sessions", ["user_id", "date"])


def downgrade() -> None:
    raise RuntimeError("Mobility plan history must not be discarded; restore the backup.")
