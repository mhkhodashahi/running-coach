---
name: project-guide
description: Modify, debug, or explain Pulse Coach's FastAPI/HTMX web app, deterministic training metrics, SQLite repositories, Garmin imports, coach workflows, or worker. Use for implementation and project setup; use review-running for review-only requests.
---

# Pulse Coach Project Guide

## Start Here

Read root `AGENTS.md`, then `.codex/agent.md`. They take precedence over this
skill. Read the relevant milestone in `docs/PLAN.md`; do not start adjacent work.
All paths below are relative to the repository root.

Use `docs/architecture.md` for boundaries, `docs/metrics.md` for definitions,
`docs/upgrade.md` for migrations, and `docs/worker.md` for operations.
Treat historical audit sections and superseded ADRs as history, not instructions.
For review-only requests, use `$review-running` without editing code.

## Where Behavior Lives

| Concern | Ownership |
| --- | --- |
| Web assembly and HTTP | `web/app.py`, `web/routes/pages.py` |
| Presentation | `web/view_models/`, `web/templates/`, `web/charts.py` |
| UI assets | `web/static/css/v2.css`, self-hosted fonts and HTMX in `web/static/` |
| Metrics and dated inputs | `metrics/`, `db/repositories/metrics.py` |
| Daily intensity and ranking | `coach/decision.py`, `services/daily_decision_service.py` |
| Shared usual-week reference and estimates | `coach/load_model.py` |
| Pure weekly safety checks | `coach/week_rules.py` |
| Drafting, approval and workouts | `coach/planning.py`, `coach/proposals.py`, `coach/workouts.py` |
| Facts, opinions and verification | `services/coach_facts.py`, `services/coach_opinion.py`, `services/number_verifier.py` |
| Chat, tools and provider adapters | `coach/agent.py`, `coach/tools.py`, `llm/` |
| Briefs and shared review composition | `services/morning_brief.py`, `services/review_service.py` |
| Persistence and migrations | `db/repositories/`, `db/session.py`, `db/migrations/versions/` |
| Garmin normalization and imports | `services/garmin_normalization.py`, `services/garmin_client.py`, `services/import_service.py` |
| Scheduling and Telegram | `worker/`, `services/telegram_service.py`, `services/telegram_chatbot.py` |

Streamlit is removed. Do not recreate old pages, `app/` or `ui/` for a new feature.
FIT import remains unresolved; do not describe it as implemented.

## Change Workflow

- Inspect callers, repository methods and nearby tests before choosing the change.
  List intended files first. Prefer the existing domain boundary over another wrapper.
- Keep routes thin and presentation in view models. SQL and ORM mutations belong
  in user-scoped repositories; application services own sessions and transactions.
  `db/repository.py` is a compatibility facade, not the home for new queries.
- Pass the same `Settings` and explicit database URL through each workflow and
  provider. Do not let an injected provider fall back to a global database for
  approval or usage storage. Mutable install files resolve through PULSE_HOME.
- Schema and index changes need Alembic, matching model metadata, preservation
  tests and the backup-first runner. Startup only checks the revision. Test on
  disposable data; a feature request does not authorize upgrading the working DB.
- Preserve protected tables and old payloads. Opinion regeneration is explicit
  and archives the current review in the same transaction.
- Keep decisions and workout numbers code-owned. The opinion verifier checks
  units, signs and rounding; test reversed deltas as well as invented values.
  Preserve per-user locks, call accounting, provider approvals and repair limits.
- Plan edits remain proposals until accepted. Validate the exact selected groups,
  check the plan version, snapshot before apply and preserve undo. Fixed/protected
  sessions and logged activities must retain their existing protections.
- Memories and notes are bounded, escaped athlete data, never instructions.
  Keep active rules enforced by code and extracted memory suggestions opt-in.
- Keep Garmin auth/orchestration separate from payload/unit normalization.
  Pin stored kilometres/minutes to display tests; do not infer units from magnitude.
- Scheduled jobs remain idempotent and never approve proposals. Reuse guarded
  application workflows for manual digests, not a second model-decision pipeline.
- For slow pages, profile on a disposable copy and inspect query plans first.
  Reuse shared load calculations. `metrics/calculation_scope.py` caches only within
  an explicit render; do not replace it with an unbounded cross-request cache.
- For HTMX actions, preserve loading, error and no-JS states. Respect v2 tokens,
  accessible statuses and phone safe areas. No LLM calls on page render. Running
  maps are opt-in Google calls; preserve their coordinate-sharing disclosure.

## Verification

Run focused tests for the touched behavior, then the required full checks:

```bash
python -m pytest
python -m ruff check .
python -m compileall -q analytics coach db llm metrics scripts services utils web worker tests config.py
```

Use the repository's virtual environment when needed. If a tool is unavailable,
report the unrun check instead of treating a syntax check as a test pass.

Choose additional checks by risk:
- Persistence: repository scoping/rollback tests and migration preservation/up/down.
- Coach: fake providers, numeric verification, limits, retry/fallback and approval tests.
- UI: TestClient plus private browser captures at the requested viewports.
- Performance: identical before/after outputs, query counts/plans and scoped-cache freshness.
- Packaging: `poetry check --lock`, `poetry build`, then
  `python -m scripts.check_distribution dist/<wheel>.whl`.
- Release: follow `docs/release.md`; a secret scan is not a personal-data audit.
  Never rewrite Git history or force-push without separate explicit approval.

Do not send live LLM, Garmin or Telegram requests as a routine verification step.
Report files changed, checks and failures, and any manual migration needed.
