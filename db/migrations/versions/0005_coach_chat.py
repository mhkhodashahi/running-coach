"""Persist coach chat turns and count each LLM request without touching old rows."""

import sqlalchemy as sa
from alembic import op

revision = "0005_coach_chat"
down_revision = "0004_coach_opinion_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "coach_chat_turns" not in tables:
        op.create_table(
        "coach_chat_turns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("activity_ids_json", sa.Text(), nullable=False),
        sa.Column("tool_calls_json", sa.Text(), nullable=False),
        sa.Column("model_provider", sa.String(32), nullable=False),
        sa.Column("model_name", sa.String(80), nullable=False),
        sa.Column("prompt_version", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_coach_chat_turns_user_id", "coach_chat_turns", ["user_id"])
    if "coach_llm_calls" not in tables:
        op.create_table(
        "coach_llm_calls",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("local_day", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_coach_llm_calls_user_id", "coach_llm_calls", ["user_id"])
        op.create_index("ix_coach_llm_calls_local_day", "coach_llm_calls", ["local_day"])


def downgrade() -> None:
    raise RuntimeError("Coach chat history must not be discarded; restore the backup.")
