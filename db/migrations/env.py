"""Migrations run only through the backup-aware runner."""

from alembic import context

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("Use python -m scripts.upgrade_db --db PATH (automatic backup required).")

context.configure(connection=connection, target_metadata=None, transactional_ddl=True)
with context.begin_transaction():
    context.run_migrations()
