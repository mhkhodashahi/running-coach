"""Add athlete-owned coach memories and migrate the legacy memory file."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0018_coach_memories"
down_revision = "0017_detailed_workouts"
branch_labels = None
depends_on = None

CATEGORY = "other"


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
    _copy_legacy_file()


def _copy_legacy_file() -> None:
    bind = op.get_bind()
    user_id = bind.execute(sa.text("SELECT id FROM users ORDER BY id LIMIT 1")).scalar()
    if user_id is None:
        return
    database = Path(bind.engine.url.database or "").resolve()
    legacy = database.parent.parent / "data" / "couch_running_memory.md"
    if not legacy.exists():
        return
    text = legacy.read_text(encoding="utf-8")
    entries: list[str] = []
    for line in text.splitlines():
        if not line.startswith("- "):
            continue
        value = line[2:].strip()
        if not value or value.lower() in {"none yet", "none yet."}:
            continue
        entries.append(value[:200])
    now = datetime.now(UTC).replace(tzinfo=None)
    for value in entries:
        bind.execute(sa.text(
            "INSERT INTO coach_memories(user_id,category,text,rule_json,status,source,valid_from,"
            "valid_until,created_at,updated_at,last_used_at) "
            "VALUES(:uid,:category,:text,NULL,'active','migrated',:today,NULL,:now,:now,NULL)"),
            {"uid": user_id, "category": CATEGORY, "text": value,
             "today": date.today(), "now": now})


def downgrade() -> None:
    op.drop_table("coach_memory_extraction_state")
    op.drop_column("notification_settings", "suggest_memories_llm")
    op.drop_index("ix_coach_memory_history_memory_id", table_name="coach_memory_history")
    op.drop_table("coach_memory_history")
    op.drop_index("ix_coach_memories_user_id", table_name="coach_memories")
    op.drop_table("coach_memories")
