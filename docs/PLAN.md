# Running Coach Implementation Plan

Status: milestone 4a complete; milestone 4b-1 implemented on 2026-10-22. Root `AGENTS.md` contains the target architecture, opinion contract and decisions. Later milestones remain unstarted.

## Current State

### Modules and entry points

| Area | Existing modules | Current responsibility |
| --- | --- | --- |
| Configuration | `config.py`, `.env.example`, `pyproject.toml` | Environment settings, dependency and CLI declarations. |
| Web UI | `app/main.py`, `app/dashboard.py`, `app/pages/`, `ui/components.py`, `ui/sidebar.py`, `ui/charts.py`, `ui/google_maps.py` | Streamlit navigation, Today/Training/Health/Goal/Coach/Goals/Key Sessions pages, hidden Activity Details page, charts and maps. |
| Metrics | `analytics/performance.py`, `services/coaching_engine.py`, `services/hr_zones.py` | Deterministic mileage, recovery/readiness/fatigue, projections, rule guidance, HR zone summaries. |
| Persistence | `db/models.py`, `db/repository.py`, `db/session.py`, `db/setup.py` | SQLAlchemy models, SQLite queries/transactions, schema creation and ad hoc compatibility SQL. |
| Garmin/CSV ingestion | `services/garmin_client.py`, `services/garmin_normalization.py`, `services/garmin_models.py`, `services/import_service.py` | `garminconnect` live activity/health/detail sync; CSV activity/health import; normalization and upsert. No FIT parser or FIT upload path was found. |
| Coaching and LLM | `services/activity_coaching_service.py`, `services/coaching_workflow.py`, `services/coaching_prompts.py`, `services/llm_workflow.py`, `services/running_coach_memory.py`, `services/training_context_service.py`, `services/training_chat_service.py`, `services/goal_service.py`, `services/prediction_snapshot_service.py`, `llm/` | Per-run coach opinion, daily/weekly decisions, prompt context, JSON clients/schemas, local memory file, DB-backed chat, goal and prediction history. |
| Delivery and jobs | `services/telegram_service.py`, `services/telegram_chatbot.py`, `utils/garmin_sync_cli.py`, `utils/daily_digest_cli.py`, `utils/telegram_chat_cli.py`, `scripts/`, `launchd/` | Telegram send/long polling and local CLI/launchd schedules. `launchd/` is ignored and its local plists contain absolute machine paths. |
| Verification and packaging | `tests/`, `.github/workflows/`, `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE`, `docs/upgrade.md`, `docs/adr/` | Pytest, Ruff, syntax and secret-scan CI; AGPL-3.0 package documentation and lightweight upgrade guidance. |

### SQLite schema

The following is the **observed** schema of the runtime `db/running_coach.db` on 2026-10-21. It is a private local file, not a distributable fixture. New databases created from `db/models.py` have 13 modeled tables. The two `body_scan*` tables below exist only in this observed database, not in current models; preserve them until ownership and migration are confirmed.

| Table | Columns |
| --- | --- |
| `users` | `id`, `age`, `gender`, `weight`, `height`, `max_hr`, `marathon_goal_time`, `marathon_date`, `name`, `training_days_per_week`, `injury_notes`, `running_goal_time`, `running_date` |
| `activities` | `id`, `user_id`, `external_id`, `date`, `type`, `distance`, `duration`, `pace`, `avg_hr`, `max_hr`, `cadence`, `elevation`, `training_effect`, `aerobic_effect`, `anaerobic_effect`, `notes`, `activity_name` |
| `activity_track_points` | `id`, `activity_id`, `point_index`, `timestamp`, `elapsed_seconds`, `distance_km`, `latitude`, `longitude`, `elevation`, `pace`, `speed`, `heart_rate`, `cadence` |
| `activity_laps` | `id`, `activity_id`, `lap_index`, `lap_type`, `start_time`, `duration`, `distance`, `pace`, `avg_hr`, `max_hr`, `elevation_gain`, `avg_cadence` |
| `health_metrics` | `id`, `user_id`, `date`, `sleep_duration`, `sleep_score`, `resting_hr`, `hrv`, `stress`, `body_battery`, `recovery_time`, `vo2max` |
| `goals` | `id`, `user_id`, `name`, `goal_type`, `target_distance_km`, `target_time_minutes`, `target_date`, `priority`, `status`, `is_active`, `notes`, `created_at`, `updated_at` |
| `prediction_snapshots` | `id`, `user_id`, `activity_id`, `goal_id`, `prediction_date`, `race_distance_km`, `predicted_time_minutes`, `predicted_pace`, `gap_minutes`, `confidence`, `payload_json`, `created_at` |
| `activity_coaching_insights` | `id`, `user_id`, `activity_id`, `summary`, `payload_json`, `prompt_context_json`, `model_provider`, `model_name`, `created_at`, `updated_at` |
| `coaching_decisions` | `id`, `user_id`, `goal_id`, `decision_type`, `decision_date`, `summary`, `risk_level`, `payload_json`, `email_subject`, `email_body`, `created_at` |
| `email_deliveries` | `id`, `user_id`, `coaching_decision_id`, `recipient`, `subject`, `status`, `provider_message`, `sent_at` |
| `llm_memory` | `id`, `user_id`, `date`, `context_summary`, `recommendations`, `fatigue_flag`, `confidence_score` |
| `nutrition_entries` | `id`, `user_id`, `entry_date`, `meal_type`, `food_name`, `calories`, `protein_g`, `carbs_g`, `fat_g`, `notes`, `created_at` |
| `garmin_sync_status` | `user_id`, `last_synced_at` |
| `body_scans` (unmodeled in current code) | `id`, `user_id`, `scan_date`, `view`, `status`, `source_image_path`, `preview_image_path`, `mesh_path`, `keypoints_json`, `measurements_json`, `pose_quality`, `processor_name`, `error_message`, `consent_to_store_image`, `notes`, `created_at`, `updated_at` |
| `body_scan_insights` (unmodeled in current code) | `id`, `user_id`, `insight_date`, `scan_ids_json`, `summary`, `payload_json`, `prompt_context_json`, `model_provider`, `model_name`, `created_at` |

The runtime `users.marathon_goal_time` and `users.marathon_date` columns are legacy columns absent from the current `User` model. `db/setup.py` copies their values into newer running-goal fields. `db/marathon_coach.db` also exists locally; `config.py` redirects a `DB_PATH` ending in `marathon_coach.db` to `running_coach.db`, so an old file is **not** automatically imported into the active one.

### Existing LLM Coach Opinion

`app/pages/8_Activity_Detail.py` displays the "LLM Coach Opinion" panel and invokes `ActivityCoachingService.generate_for_activity()` on an explicit button click. `services/activity_coaching_service.py` checks run type and available detail/notes, loads profile, goal, activities, health, laps, stream summaries, and local running memory; it builds a prompt, calls the selected LLM via `llm/factory.py` and `services/llm_workflow.py`, normalizes the result to `ActivityCoachInsightSchema` in `llm/schemas.py`, and stores it through `db/repository.py` in `activity_coaching_insights`. The row contains `summary`, `payload_json`, `prompt_context_json`, model metadata, and timestamps. A unique `activity_id` and a pre-generation lookup make it one-time by default. The separate `coaching_decisions` table holds daily/weekly digests, not per-run opinions.

Current per-run JSON keys are `overall_assessment`, `what_was_good`, `mistakes_or_inefficiencies`, `pacing_analysis`, `aerobic_efficiency_analysis`, `recovery_analysis`, `mental_performance_insights`, `training_recommendations`, `brutally_honest_conclusion`, `evidence`, and `confidence`. The schema is permissive (most fields default to empty); stored payloads have no explicit JSON schema version.

## Gaps to Validate Against AGENTS.md

The source "Target architecture" and "Coach opinion JSON" text is missing, so the following are **observed capabilities and candidate gaps**, not claims of a verified mismatch with that target.

| Area | Current code | Candidate gap / decision |
| --- | --- | --- |
| Data and migrations | SQLite/SQLAlchemy with `create_all` and a few repeated `ALTER`/`UPDATE` statements in `db/setup.py`; no versioned migration runner. | Define target tables/columns, migration versions, backfill and rollback rules before changing existing files. Preserve unmodeled and legacy data. |
| Import | Garmin Connect and CSV are implemented; FIT import was not found in source or dependencies. | Confirm FIT is required and whether it must include laps, GPS, HR, and timezone handling. Map FIT IDs to existing `external_id` without collisions. |
| Metrics | `analytics/performance.py` computes snapshots at read time; predictions alone have persisted snapshots. Some metrics use current calendar windows and others the latest stored date. | Specify metric definitions, freshness/provenance, historical-as-of behavior, and test fixtures before adding a new metrics engine or storage. |
| Coach opinion JSON | A one-time Pydantic-normalized opinion exists, but its exact keys cannot be compared with the missing target contract; no schema version is stored. | Obtain target JSON schema and define a lossless reader/migration for old `payload_json` before changing writers or UI. |
| Coach tools and chat | Telegram chat compacts DB context into one prompt; deterministic rule guidance and provider-size/privacy guards exist. No tool-call registry or web chat surface was found. | Define allowed read-only tools, user/goal scope, grounding evidence, missing-data behavior, and action boundaries. |
| Web UI | Streamlit UI and Activity Details already work; no separate web API/frontend package exists. | Confirm whether target means extending Streamlit or introducing a separate frontend/API; keep existing activity, goal, and sync workflows reachable. |
| Scheduler and Telegram | Local shell/launchd jobs and Telegram send/polling exist. | Define portable scheduling, retry/idempotency, timezone and duplicate-send behavior; preserve configured-recipient authorization. |
| Open-source release | AGPL-3.0, package metadata, README, tests, CI, and secret scan exist. | Update stale docs, portable job examples, demo-data behavior, and release checks. |

## Milestones

Sequence depends on the missing target contract. Acceptance criteria below are concrete checks to refine after it arrives; no milestone should rewrite stored data without a backup and compatibility test.

### 1. Schema and migrations

- Files to touch: `db/models.py`, `db/repository.py`, `db/setup.py` or new versioned migration scripts, `docs/upgrade.md`, and focused `tests/test_repository.py`/migration tests.
- Acceptance: inventory and back up existing DBs; apply migrations twice without changing rows on the second run; preserve foreign keys, Garmin `external_id`, notes, goals, predictions, opinions, `body_scan*` tables, and legacy user columns; verify a fresh DB and a copied old DB; document a restore path.
- Risks: `create_all` does not transform old tables; existing goal-name replacement can alter user-entered names; `marathon_coach.db` filename redirection can hide an old DB; dropping unmodeled body-scan tables or replacing `payload_json` would lose private data.

### 2. Metrics engine

- Files to touch: `analytics/performance.py`, `services/hr_zones.py`, `services/garmin_normalization.py`, `services/training_context_service.py`, `services/prediction_snapshot_service.py`, `tests/test_analytics.py`, and new metric fixtures/tests as needed.
- Acceptance: publish units, rolling-window boundaries, timezone/as-of semantics, missing-data rules and provenance for each target metric; deterministic outputs on fixed fixtures; current 7/28-day values exclude stale/future runs while historical snapshots remain reproducible; preserve existing prediction history.
- Risks: changing metric definitions silently changes old dashboard values, digest evidence and predictions; Garmin and FIT units/timezones can differ; recomputing old snapshots with future data would corrupt history.

### 3. Coach opinion JSON

- Status: complete. `opinion-v2.3` uses code-built facts before words, validates cited evidence, and keeps legacy opinions readable. Remote providers require explicit config approval; results documents use `[redacted]` in place of athlete values.
- Files to touch: `llm/schemas.py`, `services/activity_coaching_service.py`, `services/llm_workflow.py`, `services/coaching_prompts.py`, `db/repository.py`, `app/pages/8_Activity_Detail.py`, and `tests/test_activity_coaching_service.py`.
- Acceptance: validate against the supplied "Coach opinion JSON" contract; normalize both Ollama and OpenAI output; persist provider/model/schema version and source evidence; read pre-existing opinions without regeneration or data loss; show missing or uncertain evidence clearly; keep one opinion per activity unless a versioned replacement flow is explicitly approved.
- Risks: JSON shape changes can break old rows and rendering; one-time opinions may be low quality if source data is sparse; `prompt_context_json` and local memory contain personal training data and must be handled conservatively.

### 4. Coach tools, guardrails, and chat

- Status: 4a complete (read-only tools, bounded chat, guardrails and user-scoped surfaces). Remaining work is split below; do not start a later part implicitly.

#### 4a. Read-only coach tools, guardrails and chat

- Files: `coach/`, `services/training_chat_service.py`, `services/telegram_chatbot.py`, Streamlit Coach and Activity Detail pages, and their tests.
- Acceptance: approved user-scoped read tools return bounded, dated facts; chat validates numbers and evidence, handles missing data and blocks diagnosis; Telegram authorization and call limits are tested.
- Risks: prompt injection through imported notes, cross-user exposure, invented metrics and runaway token use.

#### 4b-1. Daily decision

- Status: complete. Readiness v1.2 and deterministic daily decisions are active; the athlete override remains separate.
- Files: `metrics/readiness.py`, `metrics/snapshot.py`, `coach/decision.py`, daily decision storage/service, Today and Telegram surfaces, tests and `docs/metrics.md`.
- Acceptance: readiness v1.1 uses a 3-night HRV mean (2-night minimum) while the illness flag uses last night; deterministic first-match intensity and four-sport ranking cite facts; stale health is provisional; `daily_v2` stores coach output and independent athlete override; LLM explains only and safely falls back; Today and `/today` agree.
- Risks: same-day health can arrive after a provisional decision; existing daily decision rows must remain intact; short-term HRV volatility and HR-derived team-sport load are limitations.

#### 4b-2. Weekly plan and proposals/approval/undo

- Status: complete through 4b-2d. Additive 0009 stores mobility separately without rebuilding existing plans. The cap now uses the median of up to eight complete recorded training weeks; walking is informational only. Week labels follow the week-start daily decision, and a zero-running reference habit can trigger a 30-minute rebuild run.
- Files: `db/migrations/versions/0006_weekly_plan.py` through `0009_mobility_sessions.py`, `db/models.py`, `coach/planning.py`, `coach/proposals.py`, `metrics/`, plan views, tests, `docs/metrics.md`, and `docs/weekly-plan.md`.
- Acceptance: recurring commitments, protected habits and dated sessions remain athlete-owned; fixed and protected sessions count first and are never shortened or removed by the weekly planner. The eight-week median reference excludes walking and incomplete weeks; fewer than three qualifying weeks disables only the load cap. Flexible work is shortened then dropped to fit the 110% cap, at least one rest day and at most two nonadjacent hard days. A zero-running reference habit with a running goal prompts a 30-minute easy rebuild only when it fits. Mobility is non-training, cannot link to a gym activity, and is undoable. Every change has a reason and fact IDs; dependency groups apply atomically; unsafe accepted sets refuse without writes; snapshots, stale checks and undo preserve unrelated athlete edits. Telegram stays read-only for approvals.
- Risks: unknown sport-specific TRIMP medians can prevent a draft; concurrent plan edits can stale proposals; team HR load understates jumps and sprints until 4c.

#### 4c. Effort rating and team-sport load

- Status: complete through 4c-c. Revision 0010 adds the latest activity rating and a one-prompt/one-reminder delivery marker; no existing activity or opinion is rewritten. sRPE is disabled until five usable HR-backed ratings calibrate it. Thereafter, load windows share a sport-specific scale after three HR-backed ratings for that sport; below either threshold they stay on TRIMP throughout.
- Files: `db/migrations/versions/0010_activity_efforts.py`, `services/effort_service.py`, `metrics/effort.py`, load/decision/planner paths, Telegram and Streamlit activity controls, tests, and `docs/metrics.md`.
- Acceptance: a new eligible synced session can be rated 0–10 in Telegram or the web app, changed later, and prompted at most once plus one twelve-hour reminder. Football, volleyball, and gym use calibrated sRPE alongside TRIMP; running remains TRIMP. Ratings feed hard-session detection, dated load snapshots, planner estimates, and cited coach facts. Working data remains unchanged until the owner runs the backup-first upgrade.
- Risks: effort load remains unavailable until five rated HR sessions; retrospective ratings can change a new decision after calibration. Telegram delivery depends on the bot/CLI being active.

### 5a. Web skeleton and Today

- Files: `web/`, `pyproject.toml`, `.env.example`, `README.md`, and web tests.
- Acceptance: FastAPI starts only against an upgraded database; self-hosted responsive Today shows the stored daily decision, recovery, load, plan, recent activities, override and effort rating; optional password protects all personal views. Streamlit remains available.
- Risks: today's decision can trigger an LLM request if the configured provider is enabled; personal values must never be put in tracked assets or screenshots.

### 5b. Activities and Activity Detail

- Files: `web/routes/`, `web/templates/`, `web/static/`, and web tests.
- Acceptance: browse activities, open a saved opinion and rate a session on desktop and mobile; legacy opinions stay read-only.
- Risks: route and link changes can break navigation; opinions must not regenerate automatically.

### 5c. Trends, Coach and Plan

- Files: `web/routes/`, `web/templates/`, `web/static/`, and web tests.
- Acceptance: dated trends, coach chat and proposal-based planning cover the remaining primary workflows before Streamlit retirement.
- Risks: stale metrics can look current; coach proposals must remain explicit and undoable.

### 5d. Settings and Streamlit retirement

- Files: `web/`, `config.py`, `services/`, `legacy/streamlit/`, `pyproject.toml`, `README.md`, tests, and `docs/milestone-5d-parity.md`.
- Acceptance: Settings covers profile, custom HR zones, sleep goal, goal management, Garmin sync, CSV import and read-only coach configuration; every old feature has an owner disposition in the parity document. Streamlit remains startable as an optional legacy extra, but is absent from the default run path.
- Risks: editing local configuration must preserve credentials and file permissions; sync and import must not run during page rendering; old data remains intact.

### Later

- Goal readiness and prediction as a Trends Goal card.
- Weekly kilometres and long-run progression in Trends Running.
- Key Sessions as a Quality sessions filter on Activities.
- Coach digest controls and history in milestone 6.

### 6. Scheduler and Telegram (implemented)

- Files: `worker/`, `db/migrations/versions/0011_worker_jobs.py`, `services/telegram_service.py`, `services/telegram_chatbot.py`, `services/effort_service.py`, `services/garmin_client.py`, `coach/planning.py`, `coach/proposals.py`, Settings and Coach views, `docs/worker.md`, and worker tests.
- Acceptance: one local-time worker holds a process lock; job claims make scheduled messages at-most-once; Garmin sync and morning data polling, morning/day/weekly reviews, proposal buttons, quiet hours, pause/resume and optional auto-opinions are covered by mocked tests. The worker creates proposals but never applies them. A disposable copy is upgraded before a fake-clock, fake-Telegram day run.
- Operational limit: Telegram has no idempotency key. Only explicit 429 rejections are retried; a timeout is recorded as uncertain and not resent automatically. Existing working databases need the backup-first 0011 upgrade before starting the worker or web app.

### 7. Open-source packaging

- Files to touch: `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `.env.example`, `pyproject.toml`, `.gitignore`, `docs/upgrade.md`, `.github/workflows/`, release docs, and example data/tests.
- Acceptance: fresh checkout installs and runs with demo data, no credentials required; CLI, optional services, FIT support status, migrations, and supported Python versions are accurate; `ruff`, `compileall`, `pytest`, and a redacted history secret scan pass; release artifact excludes private DBs, tokens, logs, `.env`, and local memory.
- Risks: README currently describes some older page labels; package extras and launchd examples may fail on clean systems; ignored local files can still leak through manual release archives.

## Data Safety and Secrets

- No destructive changes were made during this audit. Before implementation, copy the live SQLite file and test schema changes on that copy. Preserve old `activity_coaching_insights.payload_json` and `prompt_context_json`, `prediction_snapshots`, `activities.external_id`, user notes, and the unmodeled `body_scan*` tables.
- `.env`, `.garmin_tokens/`, `db/*.db`, logs and `data/couch_running_memory.md` exist or may exist locally and are ignored; their contents were not opened for this audit. The old `db/marathon_coach.db` should not be deleted until its ownership is confirmed.
- No obvious hard-coded credential was found in tracked source. A redacted `gitleaks git` scan of 32 commits reported no leaks. This does not prove local ignored files or every possible secret format are safe.
- Credentials are read from environment settings. OpenAI use sends summarized personal training context to a remote provider; Google Maps embeds an API key in client-side requests; Telegram Bot API calls include the bot token in the URL. Review provider/privacy boundaries and log redaction before release.

## Open Questions

1. Pending the "Decisions", "Target architecture", and "Coach opinion JSON" sections of `AGENTS.md`: which requirements, JSON fields, and legacy mapping should this plan use?
2. Is FIT import part of the target, and should it preserve raw FIT files or only normalized activities, laps and streams?
3. Should the target remain a local Streamlit app with SQLite, or move to a separate web frontend/API and/or another database?
4. Are the existing `body_scan*` tables and `db/marathon_coach.db` still user data that the migration must keep accessible?
