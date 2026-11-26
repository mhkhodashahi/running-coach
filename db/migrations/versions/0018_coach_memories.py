"""Add athlete-owned coach memories without importing unscoped files."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_coach_memories"
down_revision = "0017_detailed_workouts"
branch_labels = None
depends_on = None



def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("coach_memories"):
        op.create_table(
        "coach_memories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(24), nullable=False),
        sa.Column("text", sa.String(200), nullable=False),
        sa.Column("rule_json", sa.Text()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_until", sa.Date()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime()),
        sa.Column("suggestion_action", sa.String(16)),
        sa.Column("target_memory_id", sa.Integer(), sa.ForeignKey("coach_memories.id", ondelete="SET NULL")),
        sa.Column("suggestion_reason", sa.String(200)),
        sa.CheckConstraint(
            "category IN ('goal','schedule','preference','body','equipment','coaching_style','other')",
            name="ck_coach_memories_category"),
        sa.CheckConstraint("status IN ('active','suggested','inactive')", name="ck_coach_memories_status"),
        sa.CheckConstraint("source IN ('athlete','coach_suggestion','migrated')", name="ck_coach_memories_source"),
        sa.CheckConstraint("length(text) <= 200", name="ck_coach_memories_text_length"),
        )
    if "ix_coach_memories_user_id" not in {index["name"] for index in inspector.get_indexes("coach_memories")}:
        op.create_index("ix_coach_memories_user_id", "coach_memories", ["user_id"])
    if not inspector.has_table("coach_memory_history"):
        op.create_table(
        "coach_memory_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("memory_id", sa.Integer(),
                  sa.ForeignKey("coach_memories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("previous_text", sa.String(200), nullable=False),
        sa.Column("previous_rule_json", sa.Text()),
        sa.Column("previous_status", sa.String(16), nullable=False),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
        sa.Column("change_reason", sa.String(200), nullable=False),
        )
    if "ix_coach_memory_history_memory_id" not in {index["name"] for index in
                                                     inspector.get_indexes("coach_memory_history")}:
        op.create_index("ix_coach_memory_history_memory_id", "coach_memory_history", ["memory_id"])
    if not inspector.has_table("coach_memory_extraction_state"):
        op.create_table(
        "coach_memory_extraction_state",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("processed_through_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    if "suggest_memories_llm" not in {column["name"] for column in inspector.get_columns("notification_settings")}:
        op.add_column("notification_settings", sa.Column(
            "suggest_memories_llm", sa.Boolean(), nullable=False, server_default="0"))
    # The installation-wide markdown file has no reliable database or athlete owner.


def downgrade() -> None:
    op.drop_table("coach_memory_extraction_state")
    op.drop_column("notification_settings", "suggest_memories_llm")
    op.drop_index("ix_coach_memory_history_memory_id", table_name="coach_memory_history")
    op.drop_table("coach_memory_history")
    op.drop_index("ix_coach_memories_user_id", table_name="coach_memories")
    op.drop_table("coach_memories")
