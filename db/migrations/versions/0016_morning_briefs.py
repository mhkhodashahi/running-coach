"""Store Garmin night details and verified morning briefs additively."""

import sqlalchemy as sa
from alembic import op

revision = "0016_morning_briefs"
down_revision = "0015_timeline_notes"
branch_labels = None
depends_on = None

NIGHT_COLUMNS = {
    "sleep_deep_min": sa.Float(), "sleep_rem_min": sa.Float(),
    "sleep_light_min": sa.Float(), "sleep_awake_min": sa.Float(),
    "sleep_bedtime": sa.String(32), "sleep_wake_time": sa.String(32),
    "sleep_wakeups": sa.Integer(), "hrv_weekly_avg": sa.Float(),
    "hrv_baseline_low": sa.Float(), "hrv_baseline_high": sa.Float(),
    "hrv_status": sa.String(32), "body_battery_start": sa.Float(),
    "body_battery_end": sa.Float(), "body_battery_charged": sa.Float(),
    "breathing_rate": sa.Float(),
}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    health_columns = {item["name"] for item in inspector.get_columns("health_metrics")}
    with op.batch_alter_table("health_metrics") as batch:
        for name, column_type in NIGHT_COLUMNS.items():
            if name not in health_columns:
                batch.add_column(sa.Column(name, column_type, nullable=True))
    status_columns = {item["name"] for item in inspector.get_columns("garmin_sync_status")}
    if "night_details_backfilled_at" not in status_columns:
        op.add_column("garmin_sync_status", sa.Column("night_details_backfilled_at", sa.DateTime(), nullable=True))
    if "morning_briefs" not in inspector.get_table_names():
        op.create_table(
            "morning_briefs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("date", sa.Date(), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("sections_json", sa.Text(), nullable=False),
            sa.Column("source", sa.String(16), nullable=False),
            sa.Column("model", sa.String(128), nullable=True),
            sa.Column("prompt_version", sa.String(32), nullable=False),
            sa.Column("facts_json", sa.Text(), nullable=False),
            sa.Column("feedback", sa.String(16), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("user_id", "date", name="uq_morning_briefs_user_date"),
            sa.CheckConstraint("source IN ('ai','fallback')", name="ck_morning_briefs_source"),
            sa.CheckConstraint("feedback IS NULL OR feedback IN ('useful','not_useful')",
                               name="ck_morning_briefs_feedback"),
        )


def downgrade() -> None:
    op.drop_table("morning_briefs")
    op.drop_column("garmin_sync_status", "night_details_backfilled_at")
    with op.batch_alter_table("health_metrics") as batch:
        for name in NIGHT_COLUMNS:
            batch.drop_column(name)
