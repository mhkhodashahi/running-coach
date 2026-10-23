# Database Upgrade Guide

Running Coach now uses Alembic through a **backup-first runner**. This supersedes
the lightweight setup decision in `docs/adr/0001-lightweight-sqlite-setup.md`.
Revision 0004 adds the coach opinion v2 storage contract; 0005 adds coach chat
history and per-request counters; 0006 adds weekly plans, proposals and undo
snapshots; 0007 adds optional proposal dependency groups; 0008 adds empty
athlete-owned protected habits. Existing opinions
and logged activities are not rewritten.

## Upgrade

Stop Streamlit, Garmin sync, Telegram and scheduled jobs first. Install the new
dependencies, then run from the repository root:

```bash
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m scripts.upgrade_db --db db/running_coach.db
```

The command uses the exact path supplied: it does **not** redirect
`marathon_coach.db` to `running_coach.db`. Check the path before running it.

- Existing databases needing an upgrade are backed up automatically to
  `<database-directory>/backups/<stem>.<UTC-timestamp>.<unique-suffix>.db`.
  Override that directory with `--backup-dir /private/path/backups`.
- Backups use SQLite's online backup API, include committed WAL data, are
  integrity-checked, and are created with owner-only file permissions.
  Backup failure aborts the upgrade before stamping or modifying tables.
- An unversioned existing app database is **stamped** at `0001_baseline`.
  Stamping only adds Alembic's version metadata, never runs baseline table DDL.
- A new database runs the baseline, then revisions 2 through 6.
- Stamp and upgrade are one explicit SQLite transaction. A failure rolls back
  both schema changes and revision metadata; the backup remains available.
- Repeating an upgrade at head changes nothing and creates no extra backup.
- Only `scripts.upgrade_db` runs migrations. Streamlit, Telegram polling/chat,
  Garmin sync and digest startup perform a read-only revision check. Missing,
  unversioned or behind-head databases stop startup without creating tables,
  changing data, stamping revisions or taking backups. Run the upgrade command
  explicitly, including on first installation. Do not upgrade alongside writers.

Startup reports the resolved database path in this message:

```text
Database needs an upgrade. Stop all jobs, then run:
python -m scripts.upgrade_db --db <path>
```

A revision that does not match this application's head is also rejected rather
than silently accepted or migrated.

Raw `alembic upgrade`, `stamp`, and `downgrade` are deliberately blocked by
the migration environment without the runner's connection. Do not manually stamp
a database at head: doing so skips required changes. Destructive downgrades are
unsupported; restore the backup instead.

## Revisions and Data Risks

1. `0001_baseline`: frozen schema-only snapshot of the observed runtime database,
   including both `body_scan*` tables and `users.marathon_*`. No private rows
   are included. Fresh databases reproduce its columns, defaults, constraints
   and indexes. Existing databases are stamped, not recreated.
2. `0002_legacy_compat`: missing application tables and the former `db/setup.py`
   compatibility additions/backfills. Existing body-scan tables, including
   unknown extra columns/indexes, are untouched; absent body-scan tables are
   not added to existing databases.
3. `0003_opinion_versions`: nullable `schema_version VARCHAR(32)` and
   `prompt_version VARCHAR(80)` on `activity_coaching_insights`, without defaults
   or backfills. Existing values are NULL, meaning legacy. JSON payloads,
   prompt context and opinion timestamps are not rewritten.
4. `0004_coach_opinion_v2`: nullable `activities.planned_intent` constrained to
   recovery/easy/steady/tempo/race; nullable
   `activity_coaching_insights.validation_notes`; and the new
   `activity_coaching_opinion_history` table. No opinion or activity row is
   backfilled. Regeneration archives the previous opinion in the same
   transaction before replacing it.
5. `0005_coach_chat`: new `coach_chat_turns` table stores question, answer,
   evidence, activity IDs, tool-call names/arguments, model metadata and time;
   `coach_llm_calls` counts every chat model request, including retries and
   failures, by user and local day. No existing table or row is changed.
6. `0006_weekly_plan`: new `fixed_commitments`, `plan_sessions`,
   `plan_versions`, `plan_snapshots`, `coach_proposals`, and
   `proposal_changes` tables. Existing tables and rows are untouched.
   The earlier four-table 0006 draft was uncommitted and had not been applied
   to any real database, so there is no legacy plan table.
   Accepted changes snapshot the affected weeks before applying; undo refuses
   to overwrite later edits to affected rows.
7. `0007_proposal_groups`: adds nullable `proposal_changes.group_id`. Existing
   proposal rows remain NULL and are treated as independent groups. No backfill.
8. `0008_protected_habits`: adds `protected_habits` with user, sport, intent,
   duration, weekly frequency and active state. No rows are seeded. Existing
   plans, opinions, activities and body-scan tables are unchanged.

Revision 2 copies each non-NULL `marathon_goal_time` / `marathon_date` into
`running_goal_time` / `running_date` **only if that running field is NULL**.
Every non-NULL running value is preserved, including conflicting values and
empty strings. The fields are checked independently; no legacy columns are removed.
When `running_goal_time` is absent, its existing column-addition definition
supplies the non-NULL default `03:59:59`; that default is likewise preserved.
A newly added `running_date` is NULL and can be filled from `marathon_date`.

Revision 0002 was amended before release. A test database already upgraded
using the earlier implementation will not rerun it, nor can this change recover
values previously overwritten. To retest, restore a pre-upgrade backup to a
separate copy and run the explicit upgrade command on that copy.

All `marathon_pb` goal types still become `running_pb`. Name replacement is now
restricted to the exact old generated signature:

```sql
UPDATE goals SET name = 'Primary Running Goal'
WHERE name = 'Primary Marathon Goal'
  AND goal_type = 'marathon_pb'
  AND notes = 'Default active goal created from app settings.';
```

This runs before type conversion. Other names are preserved. There is no edit
history to distinguish a user re-entering the identical generated signature.
Previously overwritten names cannot be recovered without an older backup.

The frozen schema requires `users.marathon_goal_time` without a SQL default.
Default-user creation supplies that legacy field only when it exists; it does
not add it to newer model-only databases.

## Manual Backup

```bash
.venv/bin/python -m scripts.backup_db --db db/running_coach.db
.venv/bin/python -m scripts.backup_db --db db/running_coach.db --backup-dir /private/path/backups
```

The command prints the backup path. It fails if the source is missing rather
than creating an empty source database. Backups contain private health data;
keep them out of source control and public release archives.

## Verify on a Copy

Stop writers first. These commands read the working database to make a
consistent backup, but upgrade **only** the candidate copy:

```bash
CHECK_DIR="$(mktemp -d /tmp/running-coach-upgrade.XXXXXX)"
BACKUP="$(.venv/bin/python -m scripts.backup_db --db db/running_coach.db)"
cp "$BACKUP" "$CHECK_DIR/before.db"
cp "$BACKUP" "$CHECK_DIR/candidate.db"
.venv/bin/python -m scripts.upgrade_db --db "$CHECK_DIR/candidate.db"
sqlite3 "$CHECK_DIR/candidate.db" "SELECT version_num FROM alembic_version; PRAGMA integrity_check; PRAGMA foreign_key_check;"
```

Expect `0008_protected_habits` and `ok`. Compare `foreign_key_check` with the
pre-upgrade copy; a pre-existing violation must not be mistaken for a new one.
Compare counts, exact JSON strings and complete body-scan schemas/rows:

```bash
.venv/bin/python - "$CHECK_DIR/before.db" "$CHECK_DIR/candidate.db" <<'PY'
import sqlite3
import sys
from contextlib import closing

with closing(sqlite3.connect(sys.argv[1])) as before, closing(sqlite3.connect(sys.argv[2])) as after:
    tables = [r[0] for r in before.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'"
    )]
    for table in tables:
        quoted = '"' + table.replace('"', '""') + '"'
        assert before.execute(f"SELECT count(*) FROM {quoted}").fetchone() == after.execute(f"SELECT count(*) FROM {quoted}").fetchone(), table
        columns = {r[1] for r in before.execute(f"PRAGMA table_info({quoted})")}
        for column in ("payload_json", "prompt_context_json"):
            if column in columns:
                query = f"SELECT id, {column} FROM {quoted} ORDER BY id"
                assert before.execute(query).fetchall() == after.execute(query).fetchall(), (table, column)
        if table.startswith("body_scan"):
            query = "SELECT type, name, sql FROM sqlite_master WHERE tbl_name=? ORDER BY type, name"
            assert before.execute(query, (table,)).fetchall() == after.execute(query, (table,)).fetchall(), table
            assert before.execute(f"SELECT * FROM {quoted} ORDER BY id").fetchall() == after.execute(f"SELECT * FROM {quoted} ORDER BY id").fetchall(), table
    assert before.execute("PRAGMA foreign_key_check").fetchall() == after.execute("PRAGMA foreign_key_check").fetchall()
    for table in ("activity_coaching_opinion_history", "coach_chat_turns", "coach_llm_calls",
                  "fixed_commitments", "plan_sessions", "plan_versions", "plan_snapshots",
                  "coach_proposals", "proposal_changes"):
        if table not in tables:
            assert after.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)
print("Counts, JSON payloads, body-scan schema/data, and legacy NULL versions preserved.")
PY

shasum -a 256 "$CHECK_DIR/candidate.db"
.venv/bin/python -m scripts.upgrade_db --db "$CHECK_DIR/candidate.db"
shasum -a 256 "$CHECK_DIR/candidate.db"
```

The two hashes should match. This checks preservation, not the correctness of
your profile/goal backfill: inspect the copy's user and goal values as well.

Automated tests use invented old-schema and runtime-shaped fixtures, copied
under pytest temporary directories. They never connect to your working DB:

```bash
.venv/bin/python -m pytest tests/test_migrations.py -q
```

## Restore

Stop **all** app and job processes. Preserve the failed/current database with
the manual backup command first, if readable. Select the correct pre-upgrade
backup; restoring discards changes made after that backup. Use SQLite's backup
API to restore, rather than overwriting a database file with stale WAL sidecars:

```bash
.venv/bin/python - /absolute/path/pre-upgrade-backup.db db/running_coach.db <<'PY'
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

source = Path(sys.argv[1]).resolve(strict=True)
destination = Path(sys.argv[2]).resolve()
assert source != destination, "Backup and destination must differ"
with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as backup:
    assert backup.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    with closing(sqlite3.connect(destination)) as target:
        backup.backup(target)
        assert target.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
print("Restored:", destination)
PY
```

Restore the matching application version before restarting. If the restored
database is behind this application's head, startup will stop with the upgrade
message; it will not migrate the restored database automatically.

## Contributor Rules

Never edit an already-released revision or import live ORM models into a
historical migration. Add a new revision with
`alembic revision -m "description"`, implement its operations, update ORM fields
and repository access as needed, and add fresh/legacy preservation tests.
Do not autogenerate drops for unmodeled legacy/body-scan tables. Keep backups
mandatory for pending upgrades and document any data-changing backfills.
