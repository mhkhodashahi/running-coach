"""Add athlete timeline notes without changing existing rows."""

import sqlalchemy as sa
from alembic import op

revision = "0015_timeline_notes"
down_revision = "0014_dashboard_widgets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "timeline_notes" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "timeline_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("text", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("length(text) BETWEEN 1 AND 200", name="ck_timeline_notes_text"),
    )
    op.create_index("ix_timeline_notes_user_date", "timeline_notes", ["user_id", "date"])


def downgrade() -> None:
    op.drop_index("ix_timeline_notes_user_date", table_name="timeline_notes")
    op.drop_table("timeline_notes")
