"""Reserve version metadata without rewriting legacy opinions."""

import sqlalchemy as sa
from alembic import op

revision = "0003_opinion_versions"
down_revision = "0002_legacy_compat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("activity_coaching_insights", sa.Column("schema_version", sa.String(32), nullable=True))
    op.add_column("activity_coaching_insights", sa.Column("prompt_version", sa.String(80), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Version metadata must not be discarded; restore the backup.")
