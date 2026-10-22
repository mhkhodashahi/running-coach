# Running Coach Implementation Plan

Status: current-state audit and provisional implementation plan, 2026-10-21. Root `AGENTS.md` is present and documents the current stack. Its on-disk copy does not yet contain "Target architecture", "Coach opinion JSON", the legacy mapping, or "Decisions". Those sections are required to finalize the gap assessment, milestone acceptance criteria, and answers to questions 1 and 3. This document does not authorize a schema or application change.

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

- Files to touch: `services/training_chat_service.py`, `services/coaching_engine.py`, `services/coaching_prompts.py`, `services/llm_workflow.py`, `llm/base.py`, `llm/factory.py`, `llm/schemas.py`, `services/telegram_chatbot.py`, and `tests/test_telegram_chat.py`/new tool tests.
- Acceptance: implement only approved, user-scoped read tools with bounded output and traceable dates/units; validate tool arguments and response JSON; retain missing-data and no-diagnosis behavior; provide deterministic fallback when the LLM fails; test unauthorized Telegram chats and attempts to request out-of-scope/private data.
- Risks: prompt injection through imported notes, cross-user data exposure, model-invented metrics, runaway token/cost use, or an accidental write-capable tool.

### 5. Web UI

- Files to touch: `app/main.py`, `app/dashboard.py`, relevant `app/pages/`, `ui/components.py`, `ui/sidebar.py`, `ui/charts.py`, and navigation/UI tests; add API/frontend files only if the target explicitly requires them.
- Acceptance: a user can import/sync data, inspect dated metrics and their sources, open an activity and its saved opinion, chat with the coach, and return to goals from desktop/mobile; empty, stale, loading, and provider-unavailable states are understandable; existing workflows remain reachable.
- Risks: a framework change or route rename can break stored/deep links; UI may imply that stale metrics are current; raw health data or prompts must not leak into logs or public assets.

### 6. Scheduler and Telegram

- Files to touch: `utils/daily_digest_cli.py`, `utils/garmin_sync_cli.py`, `utils/telegram_chat_cli.py`, `services/coaching_workflow.py`, `services/telegram_service.py`, `services/telegram_chatbot.py`, `scripts/`, `launchd/`, `tests/test_telegram_chat.py`, and scheduler tests.
- Acceptance: document local timezone and schedule; repeated runs do not send duplicate digests for the same event; transient Garmin/Telegram failures retry without losing a completed import or sending twice; health-only sync remains available; recipient allowlist is enforced; job setup is portable and opt-in.
- Risks: current ignored launchd plists use machine-specific absolute paths; concurrent jobs can contend for SQLite or Garmin rate limits; Telegram tokens in request URLs and job logs require redaction.

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
