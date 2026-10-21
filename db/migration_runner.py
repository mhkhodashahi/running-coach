"""Backup-first Alembic upgrades for local SQLite databases."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import URL, create_engine, inspect

from scripts.backup_db import backup_database

BASELINE = "0001_baseline"


def migration_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).with_name("migrations")))
    return config


def upgrade_database(database: Path, backup_dir: Path | None = None) -> Path | None:
    """Upgrade to head; return the pre-upgrade backup, or None for fresh/no-op runs."""
    database = database.expanduser().resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    existed = database.exists()
    engine = create_engine(URL.create("sqlite", database=str(database)), connect_args={"timeout": 30})
    config = migration_config()
    head = ScriptDirectory.from_config(config).get_current_head()
    try:
        with engine.connect() as connection:
            # Serialize explicit upgrades and make SQLite DDL and revision stamps atomic.
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                current = MigrationContext.configure(connection).get_current_revision()
                if current == head:
                    connection.rollback()
                    return None
                if current is not None:
                    ScriptDirectory.from_config(config).get_revision(current)
                backup = backup_database(database, backup_dir) if existed else None
                config.attributes["connection"] = connection
                tables = set(inspect(connection).get_table_names()) - {"alembic_version"}
                if current is None and tables:
                    if "users" not in tables:
                        raise RuntimeError("Not a recognized Running Coach database (users table missing).")
                    command.stamp(config, BASELINE)
                command.upgrade(config, "head")
                connection.commit()
                return backup
            except BaseException:
                connection.rollback()
                raise
    finally:
        engine.dispose()
