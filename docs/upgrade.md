# Upgrade Guide

Running Coach is a local SQLite app. It does not use Alembic or another formal
database migration tool yet. Schema evolution is handled explicitly in
`db/setup.py`, as documented in `docs/adr/0001-lightweight-sqlite-setup.md`.

## Before Upgrading

1. Stop the Streamlit app and any CLI jobs.
2. Back up your local database:

```bash
cp db/running_coach.db "db/running_coach.$(date +%Y%m%d-%H%M%S).bak"
```

3. Pull or apply the new project version.
4. Install dependencies:

```bash
pip install -e ".[dev]"
```

5. Start the app or run a command that initializes the app. Startup calls
   `db.setup.init_db()`, which creates missing tables and applies the lightweight
   compatibility updates listed below.

## Current Lightweight Schema Updates

`db/setup.py` currently handles these local database updates:

- `users`: adds `name`, `training_days_per_week`, `injury_notes`,
  `running_goal_time`, and `running_date` when missing.
- `users`: copies old `marathon_goal_time` and `marathon_date` values into the
  current running-goal fields when those old columns exist.
- `goals`: renames legacy `marathon_pb` goal types and goal names to running
  terminology.
- `activities`: adds `activity_name` when missing.
- `activity_coaching_insights`: adds `updated_at` when missing.
- `prediction_snapshots`: creates the table and indexes when missing.

These updates are intentionally additive or compatibility-oriented. They should
not delete user data.

## Contributor Rules For Schema Changes

When a change adds or changes persisted data:

- Update SQLAlchemy models in `db/models.py`.
- Update repository read/write helpers in `db/repository.py`.
- Update lightweight setup SQL in `db/setup.py`.
- Add or update focused tests that exercise an older database shape when
  practical.
- Add a note to this file explaining what existing users should expect.
- Avoid destructive schema changes. If a destructive change is unavoidable,
  document the manual backup and recovery path here before merging.

## When To Adopt Alembic

Move from lightweight setup SQL to Alembic when any of these become common:

- More than a few schema changes per release.
- Data backfills become multi-step or order-dependent.
- Downgrades or repeatable named migration versions are needed.
- Multiple contributors are changing schema in parallel.
- Users need clearer release-by-release database state tracking.

Until then, keep `db/setup.py` as the single place for compatibility SQL and keep
upgrade notes in this guide.
