"""Athlete commitments, planned sessions, proposals and undo history."""

import sqlalchemy as sa
from alembic import op

revision = "0006_weekly_plan"
down_revision = "0005_coach_chat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "fixed_commitments" not in tables:
        op.create_table(
            "fixed_commitments",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("weekday", sa.Integer(), nullable=False),
            sa.Column("start_time", sa.String(5), nullable=False),
            sa.Column("sport", sa.String(16), nullable=False),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("typical_duration_min", sa.Integer(), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False),
            sa.CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_fixed_commitments_weekday"),
            sa.CheckConstraint("sport IN ('football','volleyball')", name="ck_fixed_commitments_sport"),
            sa.CheckConstraint("kind IN ('training','match')", name="ck_fixed_commitments_kind"),
            sa.UniqueConstraint("user_id", "weekday", "start_time", "sport", name="uq_fixed_commitments_slot"),
        )
        op.create_index("ix_fixed_commitments_user_id", "fixed_commitments", ["user_id"])
    if "plan_sessions" not in tables:
        op.create_table(
            "plan_sessions",
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
            sa.Column("linked_activity_id", sa.Integer(), sa.ForeignKey("activities.id")),
            sa.Column("fixed_commitment_id", sa.Integer(), sa.ForeignKey("fixed_commitments.id")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint("sport IN ('running','gym','football','volleyball')", name="ck_plan_sessions_sport"),
            sa.CheckConstraint("origin IN ('athlete','coach','fixed')", name="ck_plan_sessions_origin"),
            sa.CheckConstraint("status IN ('planned','done','skipped')", name="ck_plan_sessions_status"),
        )
        op.create_index("ix_plan_sessions_user_date", "plan_sessions", ["user_id", "date"])
        op.create_index("ix_plan_sessions_fixed_commitment_id", "plan_sessions", ["fixed_commitment_id"])
        op.create_index("ix_plan_sessions_linked_activity_id", "plan_sessions", ["linked_activity_id"])
    if "plan_versions" not in tables:
        op.create_table(
            "plan_versions",
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
            sa.Column("version", sa.Integer(), nullable=False),
        )
    if "plan_snapshots" not in tables:
        op.create_table(
            "plan_snapshots",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("version_before", sa.Integer(), nullable=False),
            sa.Column("version_after", sa.Integer(), nullable=False),
            sa.Column("snapshot_json", sa.Text(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("undone_at", sa.DateTime()),
        )
        op.create_index("ix_plan_snapshots_user_id", "plan_snapshots", ["user_id"])
    if "coach_proposals" not in tables:
        op.create_table(
            "coach_proposals",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("base_version", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(24), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("facts_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint("kind IN ('weekly_plan','change')", name="ck_coach_proposals_kind"),
            sa.CheckConstraint("status IN ('pending','applied','partially_applied','dismissed','stale','superseded')",
                               name="ck_coach_proposals_status"),
        )
        op.create_index("ix_coach_proposals_user_id", "coach_proposals", ["user_id"])
    if "proposal_changes" not in tables:
        op.create_table(
            "proposal_changes",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("proposal_id", sa.Integer(), sa.ForeignKey("coach_proposals.id"), nullable=False),
            sa.Column("change_type", sa.String(16), nullable=False),
            sa.Column("session_json", sa.Text(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("fact_ids_json", sa.Text(), nullable=False),
            sa.Column("decision", sa.String(16), nullable=False),
            sa.CheckConstraint("change_type IN ('add','modify','remove')", name="ck_proposal_changes_type"),
            sa.CheckConstraint("decision IN ('pending','accepted','rejected')", name="ck_proposal_changes_decision"),
        )
        op.create_index("ix_proposal_changes_proposal_id", "proposal_changes", ["proposal_id"])


def downgrade() -> None:
    raise RuntimeError("Plan and proposal history must not be discarded; restore the backup.")
