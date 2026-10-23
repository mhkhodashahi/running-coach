"""Add optional dependency groups to proposal changes without rewriting rows."""

import sqlalchemy as sa
from alembic import op

revision = "0007_proposal_groups"
down_revision = "0006_weekly_plan"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("proposal_changes")}
    if "group_id" not in columns:
        op.add_column("proposal_changes", sa.Column("group_id", sa.String(64), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Proposal grouping history must not be discarded; restore the backup.")
