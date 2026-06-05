# ADR 0001: Lightweight SQLite Setup

## Status

Accepted

## Context

Running Coach is a local Streamlit application backed by SQLite. The project
does not currently use a real database migration tool. Existing setup relies on
SQLAlchemy model creation plus small `ALTER TABLE` or `CREATE TABLE IF NOT
EXISTS` fallbacks for older local databases.

## Decision

Keep lightweight database setup centralized in `db/setup.py` until the project
adopts a real migration tool. Pages and services should call repository modules
for persistence and should not create tables themselves.

## Consequences

Schema evolution remains simple for a local app, but every new table or column
must update models, repository functions, setup fallback SQL, and focused tests
together.
