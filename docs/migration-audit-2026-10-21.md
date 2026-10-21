# Milestone 1 Migration Audit

Audit date: 2026-10-21. This records the completed audit and retest of the
amended revision `0002_legacy_compat`; it is not a fresh check of current state.
The amended revision copies legacy marathon fields only when the corresponding
running field is NULL.

## 1. Running Processes

None matching Streamlit, Telegram bot, Garmin sync, or digest were found by
the process check before database inspection. No processes were killed.

## 2. Working DB Status

`db/running_coach.db`: version `0003_opinion_versions`, read through a read-only
connection.

## 3. Pre-upgrade Backup Used

- Path: `db/backups/running_coach.20261021T141509.092731Z.iyjjez_z.db`
- Creation timestamp encoded in filename: `2026-10-21 14:15:09.092731 UTC`
- File modification timestamp: `2026-10-21 14:15:09.133021 UTC`
- This was the only backup listed and had no `alembic_version` table.

## 4. Overwritten Values

None found. The following query returned zero rows in the pre-upgrade backup:

```sql
SELECT id, marathon_goal_time, running_goal_time, marathon_date, running_date
FROM users
WHERE (marathon_goal_time IS NOT NULL AND marathon_goal_time IS NOT running_goal_time)
   OR (marathon_date IS NOT NULL AND marathon_date IS NOT running_date);
```

There were no differing running-goal values for the old backfill to overwrite
relative to this backup, and no affected users to compare or restore.

## 5. Repair

Not needed. No restore SQL was prepared or applied, and no restore approval
was requested.

## 6. Retest on Copy

The pre-upgrade backup was copied to `before.db` and `candidate.db` in a new
temporary directory. Only the candidate was upgraded with `scripts.upgrade_db`.

| Check | Result | Output |
| --- | --- | --- |
| Version | PASS | `0003_opinion_versions` |
| Integrity | PASS | `PRAGMA integrity_check`: `ok` |
| Foreign keys | FAIL | Four violations, identical in the pre-upgrade and upgraded copies |
| Preservation | PASS | All 15 original table counts, six JSON columns, body-scan schemas and rows, and legacy NULL opinion versions preserved |
| Repeat-upgrade hashes | PASS | SHA256 unchanged after the second upgrade |
| Running goals preserved | PASS | Both non-NULL running fields unchanged; the mismatch query returned zero rows on the candidate |
| App startup check | PASS | Candidate accepted as up to date without starting Streamlit or modifying the database |

The JSON comparison checked exact `payload_json` and `prompt_context_json`
strings, not just parsed equivalents. Body-scan checks included schema objects
and complete rows without printing their contents. Both `schema_version` and
`prompt_version` remained NULL on legacy activity opinions.

SHA256 before and after the second upgrade, also unchanged after tests:

```text
5ed9fb4f17626eb2f4833429d7a19e0c38ab50e09b966c539fc65f2020f52439
```

## 7. Quality Checks

Checks ran in a temporary source copy containing the checkout's existing
uncommitted changes. Tests used temporary databases, with `DB_PATH` directed
to the candidate and pytest artifacts contained in the audit directory.

| Check | Result | Summary |
| --- | --- | --- |
| Ruff | PASS | `All checks passed!` |
| Compileall | PASS | Exit code 0; no errors |
| Pytest | PASS | `91 passed, 1 warning in 3.01s` |

Compileall covered `app analytics db llm services ui utils scripts tests`.
Pytest ran the entire suite. The warning was the existing SQLAlchemy
nutrition-delete warning: one row expected, zero matched.

## 8. Problems and Unexpected Findings

- Four existing `coaching_decisions` references point to missing `goals`.
  The same four foreign-key violations were present before migration; the
  migration did not introduce them. SQLite integrity checking still passed.
- Proposed follow-up: investigate those references and recover the original
  goals from a known-good source before considering a separately approved
  data repair. No rows were deleted, relinked, or fabricated during this audit.
- `db/running_coach.db`, `db/marathon_coach.db`, and the original backup retained
  identical SHA256 hashes and modification timestamps throughout the copy
  retest and checks. No files were added to `db/backups/`.
- No application code was changed. This report was added afterward to record
  the results.

## 9. Temporary Directory

`/tmp/running-coach-migration-audit-mccc9a3u`

On macOS this resolves under `/private/tmp/`. It contains `before.db`,
`candidate.db`, the candidate's automatic backup, a source copy, pytest
artifacts, and protected-file fingerprints. It contains private data and must
not be committed or published. The directory was left in place for review and
can be deleted when no longer needed.
