"""Add planned intent, opinion history and validation notes without backfills."""

import sqlalchemy as sa
from alembic import op

revision = "0004_coach_opinion_v2"
down_revision = "0003_opinion_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    activity_columns = {row[1] for row in bind.exec_driver_sql("PRAGMA table_info(activities)")}
    opinion_columns = {row[1] for row in bind.exec_driver_sql("PRAGMA table_info(activity_coaching_insights)")}
    if "planned_intent" not in activity_columns:
        op.execute("ALTER TABLE activities ADD COLUMN planned_intent VARCHAR(16) "
                   "CONSTRAINT ck_activities_planned_intent "
                   "CHECK (planned_intent IN ('recovery','easy','steady','tempo','race'))")
    if "validation_notes" not in opinion_columns:
        op.add_column("activity_coaching_insights", sa.Column("validation_notes", sa.Text(), nullable=True))
    if "activity_coaching_opinion_history" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "activity_coaching_opinion_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("activity_id", sa.Integer(), sa.ForeignKey("activities.id"), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("prompt_context_json", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.String(32)),
        sa.Column("prompt_version", sa.String(80)),
        sa.Column("model_provider", sa.String(32)),
        sa.Column("model_name", sa.String(80)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("replaced_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_activity_coaching_opinion_history_activity_id", "activity_coaching_opinion_history", ["activity_id"])


def downgrade() -> None:
    raise RuntimeError("Opinion history and intent must not be discarded; restore the backup.")
