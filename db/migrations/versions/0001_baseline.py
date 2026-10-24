"""Observed runtime schema, including legacy and unmodeled tables."""

from alembic import op
from sqlalchemy import inspect

from db.migrations.schema import baseline_metadata

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    if set(inspect(connection).get_table_names()) - {"alembic_version"}:
        raise RuntimeError("Existing databases must be stamped at the baseline, not recreated.")
    baseline_metadata().create_all(connection)


def downgrade() -> None:
    raise RuntimeError("Destructive downgrades are disabled; restore the pre-upgrade backup.")
