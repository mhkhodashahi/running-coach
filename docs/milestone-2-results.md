# Metrics Engine Implementation Results

These results cover milestone 2: the metrics engine. This records the completed
implementation and verification; historical checks were not rerun when saving
this report.

## Scope

Implemented a dated metrics engine with immutable dataclasses, pure calculation
functions, provenance, and a read-only SQLite adapter and CLI. No schema,
database contents, UI, or existing `analytics/performance.py` calculations were
changed.

Included health baselines, sport mapping, Banister TRIMP, acute/chronic load,
shared HR-zone boundaries, per-sport daily and weekly loads, readiness components,
and an illness flag. Formula definitions, missing-data rules, timezone handling,
and assumptions are documented in [metrics.md](metrics.md).

## Files Changed

Added:

- `metrics/__init__.py`
- `metrics/models.py`
- `metrics/sports.py`
- `metrics/baselines.py`
- `metrics/load.py`
- `metrics/readiness.py`
- `metrics/snapshot.py`
- `metrics/reader.py`
- `metrics/report.py`
- `tests/test_metrics.py`
- `docs/metrics.md`

Updated:

- `config.py`
- `.env.example`
- `pyproject.toml`

Configuration additions: `LOCAL_TIMEZONE`, default `Europe/Berlin`, and
`SLEEP_GOAL_HOURS`, default `7.5`.

## Activity Types Found

Read-only query of the working database at implementation time:

| Activity type | Count | Category |
| --- | ---: | --- |
| cycling | [redacted] | other |
| indoor_cardio | [redacted] | gym |
| lap_swimming | [redacted] | other |
| meditation | [redacted] | excluded |
| open_water_swimming | [redacted] | other |
| running | [redacted] | running |
| soccer | [redacted] | football |
| strength_training | [redacted] | gym |
| volleyball | [redacted] | volleyball |
| walking | [redacted] | other |

All observed types are mapped. Unknown types: none.

## Seven-Day Old-versus-New Comparison

Read-only comparison for the last seven calendar dates ending on the latest
stored date, [redacted]. Readiness is scored out of 100. Load columns are
seven-day totals: old load uses arbitrary heuristic units, while new load uses
TRIMP. These load scales are not equivalent.

| Date | Old readiness | New readiness | Old load | New TRIMP |
| --- | ---: | ---: | ---: | ---: |
| [redacted] | [redacted] | [redacted] | [redacted] | [redacted] |

Coverage values are [redacted]. Coverage and calculation methods are included
in snapshot provenance. These were dated results, not current live metrics.

## Verification Results

| Check | Result |
| --- | --- |
| Ruff | PASS: all checks passed |
| Compileall | PASS: exit code 0 |
| Full pytest suite | PASS: historical run; counts and duration omitted |
| CLI strict JSON and seven-day comparison | PASS |
| Working database SHA256 across report execution | Unchanged |

The warning was the existing SQLAlchemy nutrition-delete warning: one row
expected, zero matched. Metrics tests use invented inputs and temporary SQLite
fixtures, not the working athlete database.

Run the read-only report:

```bash
.venv/bin/python -m metrics.report --date YYYY-MM-DD --compare-last-7
```

## Open Questions

1. Is health/activity evidence for a date sufficient to treat absent sessions
   as rest? The current implementation does so; completely unobserved days
   remain missing.
2. Should the load-readiness score stay at 50 below a ratio of 0.5? This is the
   current extension beyond the specified interpolation endpoints.
3. Historical HRmax currently uses the current profile because the database
   has no profile history. Historical recomputation can change after a profile
   edit; historical profile storage is outside this milestone.

## Privacy Note

Athlete-specific dates, counts, and measurements are redacted. Run the CLI
locally for current values; do not add its output to tracked documentation.
