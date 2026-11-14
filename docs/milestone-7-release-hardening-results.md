# Release Review Fixes

## Status

Code, architecture-boundary and documentation fixes from the release audit are
implemented and verified. Publication is still blocked by historical private
athlete data. No Git history was rewritten, no remote was changed and nothing
was pushed. Explicit owner approval is required before a destructive cleanup.
See [the release checklist](release.md). No schema change was needed.

## Changes

| Area | Files and outcome |
| --- | --- |
| Distribution | `pyproject.toml` includes config, coach, worker and synthetic sample CSVs; excludes runtime locks and private memory. `scripts/check_distribution.py` and tests validate/install the wheel outside the checkout. CI now builds and smoke-tests it. No new dependency. |
| Configuration | `config.py` separates the application directory from bundled package data; PULSE_HOME selects a stable local directory. `web/__main__.py` loads configuration before the bind check and uses the documented default port. Settings reads installed package metadata rather than requiring source pyproject.toml. |
| Numeric verification | `services/number_verifier.py` retains ASCII/Unicode signs and recognizes below-usual deltas. Opposite-signed values fail; sums and differences preserve signed inputs. Regression fixtures are invented. |
| Provider isolation | `llm/openai_client.py` captures the caller's Settings. `llm/factory.py` and all current provider call sites propagate them, keeping approvals, pricing and usage storage on the same installation. Tests use a fake SDK and distinct disposable databases. |
| Activity and callback isolation | Activity coaching uses explicit configured sessions and memory paths. Chat memory, effort dispatch and Telegram rating callbacks use their supplied installation instead of an implicit global destination. |
| Shared rules | `coach/load_model.py` owns the usual-week reference and load estimates; `coach/week_rules.py` owns pure weekly validation and draft application. Daily decisions and approval no longer import the planner's generation module for those rules. Existing import aliases retain compatibility. |
| Proposal conflicts | `services/daily_plan_service.py` owns daily conflict proposals, separate from weekly generation. Existing approval, stale checks, fixed commitments and undo remain covered. |
| Digest path | `services/review_service.py` composes guarded reviews for both the worker and manual digest. `services/coaching_workflow.py` and `services/coaching_engine.py` delegate instead of letting a second LLM pipeline overwrite decisions. The CLI closes its import transaction before generation. |
| Settings persistence | `db/repositories/settings_view.py` owns profile lookup, scoped goal lookup and archive mutations; web settings no longer loads or mutates ORM entities directly. |
| Guidance | Root AGENTS, `.codex/agent.md`, README, CONTRIBUTING, PLAN and the superseded SQLite ADR now describe FastAPI, scoped repositories and Alembic. Added architecture, metrics, upgrades, weekly planning, worker, retirement decisions and release docs, plus a placeholder-only launchd template. |
| Runtime files | Two runtime lock files were removed from Git tracking, not deleted from disk. Ignore rules and distribution exclusions prevent them returning. |

The owner's pre-existing staged deletions of the milestone-6k and milestone-6l
results documents were preserved, not restored or replaced.

## Compatibility Notes

- Run from the application directory, or export PULSE_HOME before launching.
  `.env`, relative DB paths and local narrative memory resolve there; samples
  are read from the installed package. Existing checkout commands keep working.
- Digest athlete-note input now directs users to Coach chat or timeline notes;
  it is not silently injected into a separate unverified model workflow.
- The manual digest uses the configured Telegram recipient, rather than sending
  athlete information to an arbitrary recipient override.
- Empty Telegram credentials in `.env.example` keep delivery disabled until configured.
- Stored reviews, chat history and domain data were not migrated or rewritten.

## Verification

- Full pytest: **777 passed**, with **191 warnings**. Existing SQLite date/datetime
  adapter deprecations and the nutrition double-delete warning remain visible.
- Ruff: passed. Compileall across active packages and tests: passed.
- `poetry check --lock`: passed. No dependency/lockfile change was required.
- Wheel and source archive builds: passed; inspected archives contain no private
  runtime artifacts such as DBs, lock files, local memory, tokens or `.env`.
- Offline installed-wheel smoke: passed for imports, fresh migration, all main
  web routes and static assets outside the checkout. Only a temporary DB was migrated.
- Gitleaks: no credential leaks detected in scanned Git history. This is not a
  personal-data clearance; the known historical running-memory blob remains.
- No live LLM, Garmin or Telegram verification calls were made.

The first regression runs exposed outdated session/memory stubs and monkeypatches
at moved module locations. Those fixtures were updated to the explicit interfaces;
no safety assertion was removed to obtain the final pass.

## How to Verify

Follow the commands in [CONTRIBUTING](../CONTRIBUTING.md), build with Poetry, then
run `python -m scripts.check_distribution dist/<wheel>.whl`. Use disposable data.
Tests assert sign preservation, provider/database isolation, shared-rule dependency
boundaries and delegated digest behavior; they are regression checks, not a formal
proof of all natural-language coaching claims or a full security assessment.

## Remaining Publication Gate

Approve and perform a private-data cleanup of every branch/tag intended for
publication, or create a reviewed clean-history public repository. Coordinate
changed commit IDs and inspect historical prompts and other deleted data as well
as the known memory file. Do not publish the existing history simply because
the source distribution and secret scanner pass.
