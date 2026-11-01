"""Persist personal chart order and options; no backfill."""

import sqlalchemy as sa
from alembic import op

revision = "0014_dashboard_widgets"
down_revision = "0013_strength_sets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "dashboard_widgets" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "dashboard_widgets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("chart_id", sa.String(40), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "position", name="uq_dashboard_widgets_position"),
    )
    op.create_index("ix_dashboard_widgets_user_id", "dashboard_widgets", ["user_id"])


def downgrade() -> None:
    op.drop_table("dashboard_widgets")
