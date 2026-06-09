# Running Coach Agent Guide

Use these repository-specific instructions for Codex work in this project.

## Project Context

- Running Coach is a local Streamlit running-coach app backed by SQLite.
- It analyzes Garmin-style activities, health and recovery metrics, goals, coaching digests, body progress scans, and running performance.
- Main Streamlit navigation entry point: `app/main.py`
- Dashboard page: `app/dashboard.py`
- Streamlit pages: `app/pages/`
- Body Progress page: `app/pages/9_Body_Progress.py`
- Activity Detail page: `app/pages/8_Activity_Detail.py`
- Reusable body scan code: `body_progress/`
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
- `$body-progress`: Body Progress, scan uploads, MediaPipe, SAM 3D Body, mesh metrics, avatar work, and scan insight privacy.

## Development Rules

- Inspect the current files before editing. Do not rely on memory of the codebase.
- Keep changes scoped to the request and follow nearby patterns.
- Preserve existing Streamlit page naming and navigation conventions. `app/main.py` uses `st.navigation`.
- Prefer reusable services/modules over page-only logic when behavior is shared.
- Do not remove Garmin, goal, Telegram, activity-detail, body-progress, or LLM workflows unless explicitly requested.
- Avoid destructive database or git commands.
- The project currently does not use real DB migrations. If adding tables/columns, keep model/repository updates and lightweight `CREATE TABLE IF NOT EXISTS` fallback SQL consistent.
- Keep analytics explainable and deterministic unless the user explicitly asks for LLM behavior.
- Preserve Garmin identifiers and titles. `activities.external_id` maps to Garmin `activityId`; `activities.activity_name` maps to Garmin `activityName` and is used in Activity Detail, analysis classification, and LLM context.
- Format user-facing pace as `m:ss` or `m:ss /km`, never decimal minutes such as `5.5`, unless a numeric value is required for calculations or chart axes. Use `format_pace()` or `format_pace_short()` from `utils/formatting.py`.
- When extracting Garmin recovery time, only trust explicitly named recovery fields such as `recoveryTime`, `latestRecoveryTime`, or `recoveryTimeHours`. Do not treat a generic Garmin `value` field as recovery time; it may be a readiness score such as `61`.
- Keep coaching prompts date-aware. AI Coach prompt payloads should include `calendar_context` from `services/coaching_prompts.py` so the LLM knows today's local weekday/date and whether the latest activity happened today.
- When changing Telegram coaching output, ensure both `build_decision_prompt` and `build_telegram_prompt` remain grounded in latest activity details, recovery metrics, active goal context, and calendar context.
- Keep body/scan outputs privacy-aware. Do not send raw image paths, checkpoint paths, command logs, stdout/stderr tails, or local machine paths to LLM prompts unless explicitly requested.
- Treat SAM mesh metrics as relative coaching/tracking proxies only. Do not present them as medical, diagnostic, body-fat, or exact anthropometric measurements.

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

## Body Progress And SAM

- The Body Progress page is gated by `.env`: set `use_sam=true` or `USE_SAM=true` to show it in navigation.
- Keep `app/pages/9_Body_Progress.py` behind `settings.use_sam`; direct access should stop when SAM mode is disabled.
- `BODY_SCAN_PROCESSOR=sam3d` runs the SAM 3D Body path.
- `BODY_SCAN_PROCESSOR=mediapipe` is the faster local pose-metrics fallback.
- SAM config is loaded from `.env`:
  - `SAM3D_REPO_DIR=sam/sam-3d-body`
  - `SAM3D_CHECKPOINT_PATH=sam/sam-3d-body/checkpoints/sam-3d-body-dinov3/model.ckpt`
  - `SAM3D_MHR_PATH=sam/sam-3d-body/checkpoints/sam-3d-body-dinov3/assets/mhr_model.pt`
  - `SAM3D_OUTPUT_DIR=data/body_scan_outputs/sam3d`
- Use `body_progress/sam3d_processor.py` for app integration.
- Use `body_progress/sam3d_cli.py` and `scripts/run_sam3d_headless.sh` for manual/headless SAM runs.
- Prefer the headless SAM runner over Meta's original `demo.py`; it avoids optional ViTDet/MoGe/SAM2 dependencies and macOS OpenGL rendering.
- If running Meta's `demo.py` manually, pass:

```bash
--detector_name "" --segmentor_name sam2 --fov_name ""
```

- Local SAM repo has CPU compatibility patches. Do not blindly overwrite them when updating the sub-repo.
- SAM output stores preview JPG, `.ply` mesh, metadata, and shape metrics.
- Mesh analysis lives in `body_progress/mesh_analysis.py`.

## LLM Scan Insights

- Body scan LLM insight workflow: `services/body_scan_insight_service.py`.
- LLM response schema: `llm/schemas.py` (`BodyScanInsightSchema`).
- Stored insight history table: `body_scan_insights`.
- The scan insight prompt should send only coaching-relevant data:
  - scan date/view/status/notes
  - processor name
  - pose quality and posture metrics
  - SAM shape metrics such as height/width/depth proxies, ratios, balance, vertex/face counts
  - prior insight summaries
  - athlete's focus question
- Do not send runtime/debug data to the LLM:
  - `command`
  - `checkpoint_path`
  - `mhr_path`
  - `repo_dir`
  - `output_dir`
  - `metadata_path`
  - `mesh_path`
  - `stdout_tail`
  - `stderr_tail`
  - local filesystem paths
- Keep prompts conservative: no diagnosis, no body-fat estimates, no injury certainty from photos/meshes.

## UX Preferences

- Keep the app style practical and motivational: warm orange accents, rounded cards, Plotly charts, and athlete-friendly labels.
- Dashboard and analysis-style pages should answer coaching questions, not just show raw data.
- First-run/demo data should remain useful without Garmin, OpenAI, Ollama, Telegram, Google Maps, or SAM configured.
- Optional/experimental surfaces should stay setup-aware and degrade gracefully instead of failing at page load.
- Body Progress should make scan outputs understandable: preview image, scan metrics, SAM shape metrics, LLM insight history, and mesh-based avatar when available.
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

- For body progress changes, run:


- For broader changes, run:

```bash
.venv/bin/python -m pytest
```

- The local `.venv` may not have `pytest` installed. If pytest is unavailable, still run `py_compile`, `ruff`, and focused direct smoke checks for touched pure functions.
- Streamlit pages may emit `missing ScriptRunContext` warnings when executed outside `streamlit run`; those warnings are expected in bare smoke checks.
