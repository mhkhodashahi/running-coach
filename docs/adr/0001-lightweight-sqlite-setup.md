# ADR 0001: Lightweight SQLite Setup

## Status

Superseded by Alembic and the backup-first runner (milestone 1).

## Context

Running Coach is a local Streamlit application backed by SQLite. The project
does not currently use a real database migration tool. Existing setup relies on
SQLAlchemy model creation plus small `ALTER TABLE` or `CREATE TABLE IF NOT
EXISTS` fallbacks for older local databases.

## Decision

The original decision was to centralize lightweight setup in `db/setup.py`.
It is no longer active. All schema changes now use Alembic revisions through
`python -m scripts.upgrade_db`; startup checks but never changes the schema.
See [upgrade instructions](../upgrade.md).

## Consequences

Do not add `create_all`, `ALTER TABLE`, or schema-repair fallbacks to app startup.
Repositories own user-scoped persistence; migration tests preserve existing data.
