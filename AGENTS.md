# AGENTS.md — Pulse Coach

Pulse Coach is an open-source training dashboard and AI coach. It pulls Garmin data (activities, HR, HRV, sleep, Body Battery, stress) into SQLite, computes recovery and load metrics, and gives one daily decision — how hard to train and which sport — on a web app and in Telegram.

Read this file before every task. If a task conflicts with it, stop and say so.

## Working rules for agents

- One task = one milestone from `docs/PLAN.md`. Do not start the next milestone unasked.
- Before coding, list the files you will change. After coding, list what changed and how to verify it.
- Every new function in the metrics engine or coach layer gets a pytest test. Run the full test suite before finishing; report failures, never hide them.
- Never change the database schema without a migration file. Never drop or rewrite user data. Ask before any destructive operation.
- Never commit secrets. Garmin credentials, LLM API keys and the Telegram token live in `.env` only; `.env.example` lists the names with empty values.
- Never put personal athlete data in tracked source: no ages, weights, injury notes, custom HR zones or names in prompts or code. Read them from the `users` table or config at runtime.
- Docs you write are named after what they contain (`docs/milestone-3-results.md`), and never hold real athlete numbers; use `[redacted]` or invented examples.
- Keep the existing data import (python-garminconnect, CSV, FIT) working. If you must change it, say why first.
- Prefer small, readable modules over clever abstractions. Type hints everywhere. No new dependency without a one-line reason.

## Current stack

- Language: Python (version per `pyproject.toml`). Licence: AGPL-3.0.
- Web UI: Streamlit — `app/main.py`, `app/dashboard.py`, `app/pages/`, `ui/`. Activity detail and the coach opinion panel live in `app/pages/8_Activity_Detail.py`.
- Database: SQLite at `db/running_coach.db` via SQLAlchemy (`db/models.py`, `db/repository.py`, `db/session.py`). Schema changes are Alembic revisions, applied only by `python -m scripts.upgrade_db` (backup-first). App startup checks the version and never migrates.
- Garmin import: `services/garmin_client.py` (python-garminconnect), `services/garmin_normalization.py`, `services/import_service.py` (CSV), `utils/garmin_sync_cli.py`. FIT import: not found in code — see Decisions.
- Metrics: new engine in `metrics/` (baselines, TRIMP load, load ratio, zones, readiness, `get_daily_snapshot`); legacy `analytics/performance.py`, `services/coaching_engine.py`, `services/hr_zones.py`.
- LLM: `llm/factory.py` (OpenAI and Ollama), `services/llm_workflow.py`, schemas in `llm/schemas.py`. Per-run opinion: `services/activity_coaching_service.py` → table `activity_coaching_insights`.
- Delivery and jobs: `services/telegram_service.py`, `services/telegram_chatbot.py`, `utils/daily_digest_cli.py`, `utils/telegram_chat_cli.py`, `scripts/`, `launchd/` (local, ignored, machine-specific paths).
- Tests and CI: pytest, ruff, compileall, gitleaks secret scan in `.github/workflows/`. Run the same three locally before finishing.

## Decisions

- **UI:** stay on Streamlit for milestones 1–4. These are backend work and must not depend on the UI framework. The framework for milestone 5 is decided before it starts.
- **Migrations:** Alembic; the first revision is a baseline of the runtime schema.
- **Data you must not touch:** the unmodeled `body_scans` and `body_scan_insights` tables, legacy `users.marathon_*` columns, and the file `db/marathon_coach.db`. Keep them as they are until the owner decides otherwise.
- **Old coach opinions:** never regenerated or rewritten automatically. They are read through the legacy mapping below.
- **FIT import:** status pending. The owner believes it exists; the audit found none.
- **Sports:** `metrics/sports.py` maps `activities.type` to running | volleyball | football | gym | other | excluded. Meditation is excluded (no load, not a session). Walking is "other": it counts toward load but is never recommended. Only running, volleyball, football and gym are recommendable.
- **Readiness v1** constants live in `metrics/readiness.py` and are tuned by the owner; do not change them unasked.
- **Facts before words:** code, not the LLM, builds a facts pack for each session: rounded display values with IDs, the detected intent (from HR-zone distribution), and data-quality notes. The LLM judges and writes, and cites fact IDs; code turns those IDs into the stored `evidence`. The LLM never writes `data_notes`, never sets `intent.detected`, and never introduces a number that is not in the facts pack.
- **Decision before words:** the daily intensity (rest | easy | hard) and the sport ranking are decided by code rules in `coach/decision.py` (constants in one place, tuned by the owner). The LLM only explains the decision and cannot change it.
- **LLM provider:** the owner chooses per install (local Ollama or a remote API). Never send athlete data to a remote provider without the owner's explicit approval in config.

## Target architecture

```
sources        ingest          store      compute            coach                 deliver
Garmin API ─┐
FIT / CSV  ─┼─> sync worker ─> SQLite ─> metrics engine ─> coach agent + rules ─> web app
Goals/races ┘   (scheduler)                                (tools over the DB)    Telegram bot
```

- **Metrics engine** (pure Python, no LLM): 7- and 28-day baselines for RHR, HRV, sleep; readiness score 0–100; acute:chronic load ratio; time in HR zones; per-sport load. The LLM never computes these numbers; it receives them.
- **Coach agent**: an LLM with tools `get_daily_snapshot(date)`, `get_activity(id)` (summary, laps, samples downsampled to 10 s), `compare_sessions(id)` (same sport, distance ±15%, same route if known), `plan_week(start_date)`. Output is validated JSON (below), stored in SQLite, and only regenerated on request.
- **Guardrails** (plain code, run after the LLM): force "rest" when illness signals stack up (RHR ≥ +7 bpm vs 7-day average AND HRV ≤ −15% vs baseline); cap weekly load increase at 10%; strip any diagnosis-like wording; when in doubt, suggest seeing a doctor.

## Coach changes and approvals

- **The coach proposes, the athlete decides.** The coach never changes the plan, goals or settings by itself. Every change is a proposal: a list of changes, each with its reason and cited fact IDs, each accepted or rejected on its own. The athlete can ask for a revision in plain words.
- **Undo is always possible.** Accepting a proposal stores a snapshot of the affected plan first; "Undo last coach changes" restores it. Logged activities are never changed.
- **Stale proposals cannot overwrite.** If the plan changed after a proposal was created, the proposal is marked stale and cannot be applied; the athlete requests a fresh one.
- **Scheduled reviews only suggest.** The morning check, the 17:00 day review and the weekly review never apply anything; they end with a proposal to accept or ignore.
- **What the coach can see** is a fixed, documented list: activities, laps, samples, health metrics, the metrics snapshot, goals, planned intents, the plan, effort ratings and the running memory. Never: credentials, tokens, other users' data, raw device IDs.
- **Limits:** one coach job per user at a time, and a daily cap on LLM calls per user (config `COACH_DAILY_CALL_LIMIT`).

## Coach opinion JSON (per activity)

```json
{
  "schema_version": 2,
  "headline": "string, one sentence",
  "confidence": "high|medium|low",
  "conclusion": "string, optional — the blunt one-line takeaway",
  "assessment": "string, one paragraph",
  "intent": { "planned": "recovery|easy|steady|tempo|race|null", "detected": "recovery|easy|steady|tempo|race" },
  "verdicts": [{ "aspect": "Pacing", "rating": "good|watch|poor", "word": "Good" }],
  "worked": [{ "lead": "string", "detail": "string" }],
  "fix": [{ "lead": "string", "detail": "string" }],
  "data_notes": ["string — recording problems, never the athlete's mistakes"],
  "sections": { "pacing": "string", "aerobic": "string", "recovery": "string", "mental": "string" },
  "recommendations": [{ "text": "string", "action": "add_to_plan|reminder|none", "session": {} }],
  "evidence": [{ "metric": "string", "value": "string", "source": "string" }]
}
```

Validate with pydantic. Store with `activity_id`, `model`, `prompt_version`, `created_at`. Every number in `worked`, `fix` and `sections` must also appear in `evidence`.

Legacy rows (no `schema_version`, written by the current `ActivityCoachInsightSchema`) are read through this mapping, never rewritten:

| Legacy key | Version 2 field |
| --- | --- |
| `overall_assessment` | `assessment` |
| `what_was_good` | `worked` (each string → `lead`, empty `detail`) |
| `mistakes_or_inefficiencies` | `fix` (legacy rows have no `data_notes`) |
| `pacing_analysis`, `aerobic_efficiency_analysis`, `recovery_analysis`, `mental_performance_insights` | `sections.pacing`, `.aerobic`, `.recovery`, `.mental` |
| `training_recommendations` | `recommendations` (each string → `text`, `action: "none"`, `session: {}`) |
| `brutally_honest_conclusion` | `conclusion`; also the `headline` when no headline exists |
| `evidence` (list of strings) | `evidence` (each string → `metric: ""`, `value: <the string>`, `source: "legacy"`) |
| `confidence` (number 0–100) | `confidence`: ≥ 70 → `high`, 40–69 → `medium`, < 40 → `low`; missing or 0 → `low` |

Fields with no legacy source (`intent`, `verdicts`, `data_notes`) stay empty, and the UI hides empty sections.

## Coach voice

- Speaks as "I", addresses the athlete as "you". Short sentences, verbs first.
- Every recommendation names its evidence: metric, value, baseline. Never "you seem tired" without a number.
- Metric units, lowercase, after the number: "52 bpm", "7h 42m", "5:12 /km".
- No emoji, no exclamation marks, no medical diagnosis.
- Sports: Running, Volleyball, Football, Gym. Team sports add jump and sprint load that HR-based scores miss; say so when relevant.

## Design tokens (Pulse Coach design system)

Use these CSS variables; never hard-code colors in components. Night is the default theme.

```css
:root, [data-theme="night"] {
  --ground:#0e1113; --surface:#161a1d; --surface-raised:#1f2427; --line:#2c3337;
  --ink:#edf1ee; --ink-muted:#9ba6a1;
  --volt:#c6f432; --on-volt:#141a05; --volt-ink:#c6f432;
  --load:#ff8f45; --sleep:#93a9ff; --heart:#ff6b6b;
  --zone-1:#7d8b92; --zone-2:#4fa8d0; --zone-3:#9bd45a; --zone-4:#ffb547; --zone-5:#ff6250;
}
[data-theme="day"] {
  --ground:#f3f4ef; --surface:#ffffff; --surface-raised:#e9ebe4; --line:#d3d8cf;
  --ink:#13171a; --ink-muted:#56605b;
  --volt:#c6f432; --on-volt:#141a05; --volt-ink:#456200;
  --load:#b8501a; --sleep:#4458c8; --heart:#c9303a;
  --zone-1:#6b7880; --zone-2:#2b7fa6; --zone-3:#4f8a1e; --zone-4:#b87400; --zone-5:#c9362a;
}
:root {
  --font-sans:"Barlow","Helvetica Neue",Arial,sans-serif;
  --font-condensed:"Barlow Condensed","Arial Narrow",sans-serif;
  --space-1:4px; --space-2:8px; --space-4:16px; --space-6:24px; --space-10:40px;
  --radius-sm:6px; --radius-md:14px; --radius-pill:999px;
}
```

- Text and numbers in `--ink`; labels, units, axes in `--ink-muted`. Metric hues (`--load`, `--sleep`, `--heart`, zones) color marks only, never text.
- `--volt` is used once per screen (readiness ring or primary button), with `--on-volt` text on it.
- Numbers in Barlow Condensed with `font-variant-numeric: tabular-nums`. One 64px hero number per screen.
- No shadows; depth comes from ground → surface → surface-raised. Cards `--radius-md`, buttons and zone bars `--radius-pill`.
- Status is never color alone: always a word plus an icon. Focus ring: 2px solid `--volt-ink`, offset 2px. Touch targets ≥ 44px.
- Missing data shows "No data" plus the last sync time, never a zero.
