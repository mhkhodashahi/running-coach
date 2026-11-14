# Insights Performance

## Diagnosis

The page requested daily snapshots more than once and rebuilt the same weekly
load model for each date. Profiling a disposable copy showed weekly-model and
daily-decision computation dominated the render, with repeated track-point reads.
Adding indexes alone would not remove the repeated Python work.

The activity query used the user-only index and a temporary sort for date/id.
Finding the first sample timestamp used an activity-only index rather than a
timestamp-ordered covering index. Health already has a unique user/date index;
no duplicate health index was added.

## Changes

- `db/migrations/versions/0019_insights_indexes.py` and `db/models.py` add:
  `activities(user_id,date)`, `activity_track_points(activity_id,timestamp)`,
  and `coaching_decisions(user_id,decision_type,decision_date)`.
- `metrics/calculation_scope.py` provides explicit, context-local reuse for
  successful read-only calculations. Nothing is cached outside an active scope.
- `metrics/reader.py` and `coach/load_model.py` reuse identical calls within that
  scope. `web/trends.py` bounds it to one render. Results never survive into a
  later request, sync or rating change; database/user/date/settings remain in keys.
- Tests cover scope isolation, concurrent renders, exception cleanup, date/user
  separation, actual per-render read counts, refreshed data on the next render,
  migration upgrade/downgrade, row preservation and query-plan index use.
- `docs/PLAN.md` and `docs/upgrade.md` document the follow-up and activation.

No metrics, decision rules, imported records or stored opinions were changed.
Earlier uncommitted release-hardening edits were preserved.

## Verification

A same-process, same-copy comparison for the default range measured **42.1 s
before** versus **10.2 s after**, approximately **4.1x faster**. Both renders
produced identical view-model data. This is a local measurement, not a latency
guarantee; processing the remaining history still takes time.

The index migration ran through the backup-first runner on the disposable copy.
A backup was created, all existing row INSERT representations matched, and
SQLite integrity_check returned `ok`. The activity query no longer needs a
temporary sort; the first-timestamp query uses the new covering index.

The working database was not upgraded. To activate the indexes, stop web/worker
jobs and run `python -m scripts.upgrade_db --db db/running_coach.db`, then restart.
Startup will refuse an old schema rather than migrating automatically.

Final checks: **783 pytest tests passed**, with the existing 191 warnings visible.
Ruff, compileall and diff whitespace checks passed. The first test runs exposed
an intentionally enforced migration-runner guard and one old revision assertion;
the disposable test setup and assertion were corrected without weakening safety.
