# Architecture

Pulse Coach is a single-athlete modular monolith. Web and worker are separate
processes using one SQLite database. It is not a hosted multi-tenant service.

## Responsibilities

- `web/routes/`: parse HTTP input and render responses; `web/view_models/` shapes display data.
- `services/`: application workflows, transactions, import adapters and provider integration.
  `services/review_service.py` composes the same guarded reviews for the manual
  digest and scheduler; application services do not import worker job orchestration.
- `coach/decision.py`, `coach/week_rules.py`, `coach/workouts.py`: deterministic training rules.
- `coach/load_model.py`: shared usual-week reference and own-history load estimates;
  independent of proposal generation and LLMs.
- `coach/planning.py`: draft proposals using those rules. `coach/proposals.py` validates
  and applies explicit athlete approvals with versions and undo snapshots.
- `metrics/`: calculations and a repository-backed input adapter; no LLM calls.
- `db/repositories/`: user-scoped persistence. Callers supply the transactional session.
- `llm/`: provider clients receive the same Settings as their caller. Approval and usage
  recording must never silently select the default database instead.
- `worker/`: timed orchestration and notification. Jobs propose, never apply plan changes.

## Boundaries

Application services call domain rules and repositories, not HTML routes.
Daily decisions and approval use shared load/safety modules, not the planner's
generation pipeline. Compatibility coaching APIs delegate to guarded workflows.
`db/repository.py` remains a forwarding facade for older data consumers; do not
add new domain SQL there. Do not create empty wrappers for individual tables.

Services own transaction boundaries. Provider calls should run outside write
transactions. Settings and the database URL are passed explicitly at install
boundaries. `PULSE_HOME` selects local mutable storage independently of the
installed Python package; bundled samples are read from the package.

## Safety

Startup checks Alembic head without upgrading. The upgrade runner backs up before
changing an existing schema. Proposal apply checks the plan version and selected
changes in one transaction, then retains a snapshot for undo. Existing reviews
remain unchanged unless explicitly regenerated, which archives the old content.

Numeric verification checks supported formats, units, signs and rounding against
code-owned facts. It is not a proof that every natural-language interpretation
or recommendation is correct. Training and health advice still require judgment.

## Verification

Run pytest, Ruff and compileall. Architecture tests check repository boundaries
and shared-rule dependencies. Distribution checks install a built wheel outside
the checkout, migrate only a disposable database and render the local web UI.
All network adapters are mocked or disabled during these checks.
