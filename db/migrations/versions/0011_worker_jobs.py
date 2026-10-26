"""Durable worker schedule, message state, and local notification preferences."""

import sqlalchemy as sa
from alembic import op

revision = "0011_worker_jobs"
down_revision = "0010_activity_efforts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_settings",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("morning_enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("morning_latest", sa.String(5), nullable=False, server_default="10:00"),
        sa.Column("day_review_time", sa.String(5), nullable=False, server_default="17:00"),
        sa.Column("weekly_weekday", sa.Integer(), nullable=False, server_default="6"),
        sa.Column("weekly_time", sa.String(5), nullable=False, server_default="18:00"),
        sa.Column("quiet_start", sa.String(5), nullable=False, server_default="22:00"),
        sa.Column("quiet_end", sa.String(5), nullable=False, server_default="05:30"),
        sa.Column("morning_llm", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("day_llm", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("weekly_llm", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("paused", sa.Boolean(), nullable=False, server_default="0"),
        sa.CheckConstraint("weekly_weekday BETWEEN 0 AND 6"),
    )
    op.create_table(
        "job_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("job", sa.String(48), nullable=False),
        sa.Column("run_date", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        sa.Column("message_text", sa.Text()),
        sa.UniqueConstraint("user_id", "job", "run_date", name="uq_job_runs_user_job_day"),
    )


def downgrade() -> None:
    raise RuntimeError("Worker history must not be discarded; restore the backup.")
