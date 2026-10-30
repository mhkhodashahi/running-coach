"""Record token usage and estimated cost for each OpenAI request."""

import sqlalchemy as sa
from alembic import op

revision = "0012_openai_usage"
down_revision = "0011_worker_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "openai_api_calls" not in inspector.get_table_names():
        op.create_table(
            "openai_api_calls",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("response_id", sa.String(128)),
            sa.Column("request_kind", sa.String(32), nullable=False),
            sa.Column("model", sa.String(128), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("input_tokens", sa.Integer()),
            sa.Column("cached_input_tokens", sa.Integer()),
            sa.Column("output_tokens", sa.Integer()),
            sa.Column("total_tokens", sa.Integer()),
            sa.Column("estimated_cost_usd", sa.String(32)),
            sa.Column("input_rate_usd_per_1m", sa.String(32)),
            sa.Column("cached_input_rate_usd_per_1m", sa.String(32)),
            sa.Column("output_rate_usd_per_1m", sa.String(32)),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    inspector = sa.inspect(op.get_bind())
    if "ix_openai_api_calls_created_at" not in {
        index["name"] for index in inspector.get_indexes("openai_api_calls")
    }:
        op.create_index("ix_openai_api_calls_created_at", "openai_api_calls", ["created_at"])


def downgrade() -> None:
    raise RuntimeError("OpenAI usage history must not be discarded; restore the backup.")
