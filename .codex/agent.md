# Running Coach Agent Guide

Use these repository-specific instructions for Codex work in this project.

## Project Context

- Running Coach is a local Streamlit running-coach app backed by SQLite.
- It analyzes Garmin-style activities, health and recovery metrics, goals, coaching digests, and running performance.
- Main Streamlit navigation entry point: `app/main.py`
- Dashboard page: `app/dashboard.py`
- Streamlit pages: `app/pages/`
- Activity Detail page: `app/pages/8_Activity_Detail.py`
- Data access: `db/repository.py`, `db/session.py`, and SQLAlchemy models in `db/models.py`
- LLM providers: `llm/openai_client.py`, `llm/ollama_client.py`, selected by `llm/factory.py`
- Coaching and LLM workflows: `services/`
- UI helpers: `ui/components.py`; Plotly charts: `ui/charts.py`
- Google Maps helpers: `ui/google_maps.py`
- HR zone helpers: `services/hr_zones.py`
- Prediction history: `services/prediction_snapshot_service.py`, persisted in `prediction_snapshots`
- Per-activity LLM coach reviews: `services/activity_coaching_service.py`, persisted in `activity_coaching_insights`

## Skill Map

Prefer these skill names when invoking repo guidance:

- `$project-guide`: general Running Coach changes, debugging, setup, tests, and explanations.
- `$review-running`: code-review mode for diffs, PR-like changes, regressions, privacy leaks, and missing tests.

## Development Rules

- Inspect the current files before editing. Do not rely on memory of the codebase.
- Keep changes scoped to the request and follow nearby patterns.
- Preserve existing Streamlit page naming and navigation conventions. `app/main.py` uses `st.navigation`.
- Prefer reusable services/modules over page-only logic when behavior is shared.
- Do not remove Garmin, goal, Telegram, activity-detail, or LLM workflows unless explicitly requested.
- Avoid destructive database or git commands.
- The project currently does not use real DB migrations. If adding tables/columns, keep model/repository updates and lightweight `CREATE TABLE IF NOT EXISTS` fallback SQL consistent.
- Keep analytics explainable and deterministic unless the user explicitly asks for LLM behavior.
- Preserve Garmin identifiers and titles. `activities.external_id` maps to Garmin `activityId`; `activities.activity_name` maps to Garmin `activityName` and is used in Activity Detail, analysis classification, and LLM context.
- Format user-facing pace as `m:ss` or `m:ss /km`, never decimal minutes such as `5.5`, unless a numeric value is required for calculations or chart axes. Use `format_pace()` or `format_pace_short()` from `utils/formatting.py`.
- When extracting Garmin recovery time, only trust explicitly named recovery fields such as `recoveryTime`, `latestRecoveryTime`, or `recoveryTimeHours`. Do not treat a generic Garmin `value` field as recovery time; it may be a readiness score such as `61`.
- Keep coaching prompts date-aware. AI Coach prompt payloads should include `calendar_context` from `services/coaching_prompts.py` so the LLM knows today's local weekday/date and whether the latest activity happened today.
- When changing Telegram coaching output, ensure both `build_decision_prompt` and `build_telegram_prompt` remain grounded in latest activity details, recovery metrics, active goal context, and calendar context.

## Garmin Import And Recovery Data

- Garmin live sync lives in `services/garmin_client.py`; CSV/mock import uses `CSVGarminClient` in the same module.
- Garmin payload normalization lives in `services/garmin_normalization.py`; keep Garmin field-shape and unit conversion rules there.
- Activity rows should include `external_id`, `activity_name`, date/type/distance/duration/pace, HR/cadence/elevation/training effects, and notes.
- Health rows should include sleep, resting HR, HRV, stress, body battery, recovery time, and VO2max when available.
- `recovery_time` is displayed directly from `health_metrics.recovery_time`; the app does not calculate Garmin recovery time itself.
- If recovery time looks stuck at a score-like value, inspect `_extract_recovery_time_hours()` first and check latest DB rows:

```bash
sqlite3 db/running_coach.db "select date, recovery_time, sleep_score, body_battery from health_metrics order by date desc limit 20;"
```

- Do not overwrite user-entered notes or profile values when importing Garmin data.

## Predictions And Goals

- Live Predicted Finish is calculated in `analytics/performance.py` through `predict_finish_time_for_distance()` and `build_goal_projection()`.
- `build_training_snapshot()` recalculates the current dashboard prediction each time pages load via `load_training_bundle()`.
- Historical prediction changes are persisted in `prediction_snapshots` by `PredictionSnapshotService`.
- After CSV import, demo seed, or Garmin sync, store prediction snapshots for running activities so Activity Detail can show "Prediction After This Run" and Dashboard can show "Prediction Trend".
- Prediction snapshots should be tied to the active goal and activity when possible. They represent the prediction using data up to that activity date, not today's full future dataset.
- Keep the prediction model deterministic and explainable; do not replace it with LLM output.

## Activity Detail, Maps, And HR Zones

- Activity Detail uses Garmin activity detail streams from `activity_track_points` when available.
- Activity Detail should use `activity_name` as the display title when Garmin provides one, falling back to type/date.
- Per-run LLM coach opinions are generated only for running/trail/treadmill activities, only once per activity, and then loaded from `activity_coaching_insights`.
- Do not auto-regenerate an existing activity coach opinion. If regeneration is ever added, it must be explicit and should preserve old output or explain that it is being replaced.
- For Garmin runs with no stream/lap detail and no manual notes, block one-time coach generation rather than saving a low-context permanent review.
- Per-run coach prompts should include athlete profile, active goal, activity name, selected activity metrics, stream/lap summaries, recovery context, recent run baseline, custom HR zones, and context-engineering guidance.
- HR zone time for running/trail/treadmill/football/soccer lives in `services/hr_zones.py` and is rendered on `app/pages/8_Activity_Detail.py`.
- Max HR is stored on `User.max_hr` and can be edited from Dashboard profile and Activity Detail HR settings. HR zones and relative effort should use this saved value.
- Google Maps route display and map export helpers live in `ui/google_maps.py`.
- Do not attempt to record/export Google Maps tiles as a video. Use Google Static Maps for exact route-on-map image export and custom GPS-data canvas animation for shareable route videos.
- `Export map` should mean exact route over a Google map image. `Route video` should mean custom animated route generated from GPS points without Google map tiles.

## UX Preferences

- Keep the app style practical and motivational: warm orange accents, rounded cards, Plotly charts, and athlete-friendly labels.
- Dashboard and analysis-style pages should answer coaching questions, not just show raw data.
- First-run/demo data should remain useful without Garmin, OpenAI, Ollama, Telegram, or Google Maps configured.
- Optional/experimental surfaces should stay setup-aware and degrade gracefully instead of failing at page load.
- Avoid unexplained model jargon in user-facing text.

## Verification

Run focused checks for touched files when practical.

For Python syntax:

```bash
.venv/bin/python -m py_compile path/to/file.py
```

For linting:

```bash
.venv/bin/python -m ruff check path/to/file.py
```

- For broader changes, run:

```bash
.venv/bin/python -m pytest
```

- The local `.venv` may not have `pytest` installed. If pytest is unavailable, still run `py_compile`, `ruff`, and focused direct smoke checks for touched pure functions.
- Streamlit pages may emit `missing ScriptRunContext` warnings when executed outside `streamlit run`; those warnings are expected in bare smoke checks.
