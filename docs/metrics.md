# Dated Metrics Engine (Milestone 2)

The engine is independent of dashboard calculations and LLM workflows. It does
not create tables, migrate, seed, persist metrics, or write to SQLite.

```bash
python -m metrics.report --date 2026-10-21
python -m metrics.report --date 2026-10-21 --compare-last-7
python -m metrics.report --date 2026-10-21 --db /path/to/copy.db --user-id 1
```

`--date` is mandatory. The optional comparison covers that date and the six
preceding calendar dates. Choose the latest date in the database for a last-data
comparison, not necessarily today's date. The CLI prints strict JSON: missing
numbers are `null`, not NaN or fabricated zeros. Unknown activity types are
listed in `snapshot.unknown_types`.

## API and Contract

`metrics.get_daily_snapshot(as_of, ...)` is the read-only SQLite adapter.
`metrics.build_daily_snapshot(inputs, as_of, timezone, sleep_goal_hours)` is the
pure calculation API. All metric calculation functions take an explicit
`as_of` date; none reads the system clock. CLI argument parsing is the entry-point
exception, not a calculation. Inputs and outputs use frozen dataclasses and
tuples. Serialize the output with `dataclasses.asdict` then `json.dumps`.
The same snapshot contract can be returned by future coach tools.

Every numeric metric/flag contains `value`, `unit`, and provenance:
`sources` (tables/columns), inclusive `window_start`/`window_end`, `n_days`,
and `method`. Session HRmax and RHR are included so TRIMP can be reproduced.
Readiness includes individual component scores and normalized weights.
For baselines, `n_days` counts distinct usable dates; for load it counts
complete observed days; session metrics use 0 or 1. Overall readiness uses
the largest contributing input window count, not a count of components.
The component and baseline provenance provides the individual coverage.

## Dates, Configuration and Scope

- `LOCAL_TIMEZONE` is an IANA timezone, default `Europe/Berlin`.
- `SLEEP_GOAL_HOURS` defaults to `7.5`; it must be positive and finite.
- `DEFAULT_USER_ID` selects the athlete unless `--user-id` is supplied.
- Date-only activity/health records are already local calendar dates. They
  cannot be reassigned by timezone without source timestamps.
- Offset-aware timestamps convert to the configured timezone. Naive timestamps
  are interpreted as local time, not silently assumed to be UTC. DST intervals
  use absolute elapsed seconds. Track samples after the assessment day are
  excluded. Existing database track samples may have elapsed seconds only.
- Future activity and health dates are excluded. Session RHR is calculated
  on the session date, never using health records from later dates.
- Profile age and max HR have no historical versions. Historical snapshots use
  the current profile, explicitly identified in the HRmax method. Changes to
  the profile can therefore change a recomputed historical snapshot.
- Reads are user-scoped, parameterized and use SQLite `mode=ro` plus
  `query_only`. A missing database raises an error rather than creating it.
  The reader does not call application startup or migration code.

## Sport Mapping

`metrics/sports.py` is the sole mapping table. Types are stripped and
lowercased, then matched exactly (no substring heuristics).

| Category | Recognized types |
| --- | --- |
| running | running, trail_running, treadmill_running, treadmill, track_running, virtual_run |
| volleyball | volleyball, beach_volleyball |
| football | soccer, football |
| gym | strength_training, indoor_cardio, gym |
| other | cycling, walking, lap_swimming, open_water_swimming |
| excluded | meditation, breathwork, yoga_nidra |

Unrecognized types map to `other` and are reported separately. Unknown-type
listing covers the user's history through `as_of`; session details cover the
28-day load window. Other sports, including walking, still contribute HR-derived
load but are not recommendation candidates. Only `RECOMMENDABLE_SPORTS`
(running, volleyball, football, gym) are candidates. Excluded activities are
not sessions and contribute zero load.

## Health Baselines

For `resting_hr` (bpm), `hrv` (ms), and `sleep_duration` (hours):

| Window | Inclusive bounds | Minimum usable dates |
| --- | --- | --- |
| 7-day | as_of - 7 through as_of - 1 | 4 |
| 28-day | as_of - 28 through as_of - 1 | 14 |

Mean = sum of daily values / number of usable dates. Duplicate dates in pure
fixtures are averaged first, so they cannot satisfy a coverage threshold by
duplication. Nonfinite and nonpositive HR/HRV values are missing; zero measured
sleep is valid, negative sleep is missing. Insufficient coverage returns NULL,
with the actual `n_days` retained. No interpolation or forward-filling.

Readiness v1.2 uses the mean HRV of the three nights ending on `as_of` (at
least two distinct nights), compared with the 28-day baseline ending the day
before. Its HRV component is `clamp(70 + (hrv_3d/hrv_28d - 1)*150, 0, 100)`;
its RHR component is `clamp(70 - (rhr-rhr_7d)*7, 0, 100)`. An athlete at both
personal baselines therefore scores 70 on these components. v1.1 used the
same three-night HRV mean and factor of 150, but centred HRV and RHR on 50;
v1 used the assessment night's HRV with a factor of 250 and centre 50. Sleep
and load scoring are unchanged. Illness still compares the single
assessment-night HRV with the baseline, together with RHR. Missing three-night
coverage omits the HRV component and reweights the others; overall readiness
needs two components including HRV or RHR.
The daily decision is provisional when the requested day's sleep or HRV is
missing; it uses the latest prior complete health day, states that day and
the last sync time. The metrics snapshot API itself does not forward-fill.

## Session Load: Banister TRIMP

```text
HRr = (HR - RHR) / (HRmax - RHR)
TRIMP = sum(dt_minutes * HRr * 0.64 * exp(1.92 * HRr))
```

Units are TRIMP, not Garmin's proprietary exercise load. The requested
coefficients are used for every athlete, without sex-dependent alternatives.
The reserve fraction is not clamped: values below resting HR contribute signed
negative terms under the supplied formula; values above HRmax can exceed 1.
This is deliberate formula fidelity, not a physiological interpretation.

- HRmax: valid `users.max_hr`, else `220 - age` for a valid age. Otherwise NULL;
  no silent 188-bpm default. `HRmax <= RHR` is invalid.
- RHR: session-date 7-day baseline, else latest valid RHR on or before the
  session date. The fallback's actual date is returned, even when stale.
- Track points: sort by point index; each HR applies to the following positive
  interval. Use timestamp differences when both endpoints have timestamps,
  otherwise elapsed-second differences. Ignore duplicate/reversed intervals
  and gaps over 300 seconds. Missing HR does not bridge to the next valid HR.
  A final sample may cover the positive remaining activity duration only when
  at most 300 seconds. Intervals are bounded by recorded duration when elapsed
  time is available and by the assessment-day boundary when timestamped.
- `observed_seconds` identifies the integrated HR coverage; missing gaps are
  not extrapolated. A partial track stream produces load for observed time
  only, explicitly labeled as a track-point method.
- With no usable HR intervals, use `avg_hr` and the stored duration in minutes.
  The method is `avg_hr_duration_fallback`. Average HR is not used to invent
  time in zones. Date-only duration cannot resolve a cross-midnight session;
  fallback load is assigned to the activity's recorded local date.
- Missing HR, RHR, HRmax, or usable timing returns NULL, never a fabricated zero.
  Nonfinite parameters, nonpositive duration/HR, extreme HR above 300 bpm, and
  exponential overflow are rejected. Zero load with actual HR equal to RHR is
  mathematically valid and distinct from missing HR.

## Time in Zones

The engine calls `services.hr_zones.heart_rate_zone_bounds`; no boundaries are
redefined. For integer HRmax the existing function returns:

| Zone | HR range |
| --- | --- |
| Below Z1 | below 50% |
| Z1 Recovery | [50%, 60%) |
| Z2 Easy | [60%, 70%) |
| Z3 Steady | [70%, 80%) |
| Z4 Threshold | [80%, 90%) |
| Z5 Max | [90%, infinity) |

Seconds = sum of observed intervals assigned to a zone. Percent = zone seconds /
all observed HR seconds * 100, including Below Z1 in the denominator. An
unvisited zone is zero when a stream is available; without a usable stream
zone values are NULL. Unknown HRmax means no zone assignment. Only boundaries
are shared: the old UI helper's median-step gap imputation is not reused.

## Daily, Weekly and Acute/Chronic Load

Daily per-sport sums cover the 28 days ending on `as_of`. Weekly per-sport
sums cover four successive seven-day blocks ending on `as_of`, not ISO weeks.
All five load-bearing categories are represented. Excluded activity days count
as observed zero-load days, even without health data.

A date with health data or an activity is treated as observed. On an observed
date, a category with no recorded sessions has zero load (assumed rest for that
category). A completely unobserved date is NULL. A category with any session
whose load is unknown is NULL, not the sum of only its known sessions.
This is an explicit coverage assumption: the schema has no complete-import
marker and cannot prove that an absent activity means rest.

Weekly per-sport values sum known daily loads and report `n_days`; they remain
NULL if none are known. All-sport load uses only dates with complete load in
all categories. Thus missing days are not fabricated as zero, but partial
windows can still produce totals. Inspect coverage before interpreting them.

```text
acute   = sum of known complete daily loads, as_of - 6 through as_of
chronic = sum of known complete daily loads, as_of - 27 through as_of, divided by 4
ratio   = acute / chronic
```

Chronic and ratio are NULL below 14 observed complete days in the 28-day
window. This is a count of observed days, not merely elapsed time since the
first import. Acute is NULL if no complete day is observed. Ratio is NULL if
chronic is zero or negative. There is no extrapolation to fill missing days.
The fixed divisor 4 follows the requested formula even with 14-27 observed days.

## Readiness and Illness Flag

All scoring constants and weights live in `metrics/readiness.py`.

```text
HRV score (v1.2) = clamp(70 + (hrv_3d / hrv_28d - 1) * 150, 0, 100)
RHR score (v1.2) = clamp(70 - (rhr - rhr_7d) * 7, 0, 100)
Sleep score = clamp(sleep_hours / sleep_goal_hours * 100, 0, 100)
```

Load score is 100 in [0.8, 1.3], linear from 50 at 0.5 to 100 at 0.8,
and linear from 100 at 1.3 to 0 at 1.8. Outside those specified endpoints,
the engine holds at 50 below 0.5 and at 0 above 1.8. Missing/negative ratios have no
component score. The lower-end extension is an explicit assumption to confirm.

Weights: HRV 35, sleep 25, RHR 20, load 20. Available component weights are
normalized to sum to 1. At least two components must exist, including HRV or
RHR; otherwise overall readiness is NULL. Missing components have weight 0.

Illness flag is true when both `rhr - rhr_7d >= 7` and
`hrv / hrv_28d - 1 <= -0.15`. It is false when both comparisons are available
but their conjunction fails; NULL when an input or baseline is missing. This
flag is a deterministic signal, not a medical diagnosis.

## Legacy Comparison

`--compare-last-7` calls the unchanged legacy functions with input frames
truncated to each comparison date. Old readiness still uses its existing
defaults and latest-record windows. Old load is the seven-day sum of:

```text
distance_km * 3 + duration_minutes * 0.3 + aerobic_effect * 12 + anaerobic_effect * 16
```

That arbitrary-unit score and new TRIMP are not interchangeable. The comparison
reports both readiness scores, both load totals, the new ratio and observed-day
counts. A nonfinite legacy readiness result is represented as NULL. No old
analytics or dashboard values are modified.

## Verification

`tests/test_metrics.py` uses invented immutable inputs and temporary SQLite
fixtures. It covers formulas, window thresholds, future exclusion, timezone/DST,
track-vs-average HR, shared zones, missingness, sports, readiness reweighting,
illness thresholds, strict JSON, immutable outputs, user scoping, read-only
database bytes and CLI output. No test opens a real athlete database.

```bash
python -m ruff check .
python -m compileall -q app analytics db llm metrics services ui utils scripts tests
python -m pytest -q
```
