---
name: review-running
description: Review Pulse Coach code, diffs, architecture, or release readiness for regressions, privacy leaks, unsafe coaching, persistence errors, and missing tests. Use for review-only requests; do not implement fixes unless the user asks.
---

# Pulse Coach Code Review

## Start Here

Read root `AGENTS.md`, `.codex/agent.md` and the relevant milestone in
`docs/PLAN.md`. Consult `docs/architecture.md` for ownership and
`docs/metrics.md` for metric definitions. All paths below are repository-relative.
Do not apply obsolete Streamlit or ad hoc schema-setup guidance.

Keep the review read-only unless fixes are explicitly requested. Establish whether
you are reviewing a diff, current source, architecture, or release artifacts;
do not call a source-only inspection a production or security certification.

## Establish Evidence

Start with `git status --short`, the requested diff, and surrounding callers/tests.
Include staged and unstaged changes when reviewing the working tree. Preserve
unrelated user edits. Trace at least one affected path from surface through the
application workflow to rules and persistence before judging its boundary.

Reproduce concrete discrepancies with synthetic fixtures or disposable copies.
State the failure conditions and observable impact; do not substitute file size
or a preference for more classes for an architectural finding.

## Risk Checklist

Use only the checks relevant to the requested review.

### Persistence and Ownership

- SQL/ORM mutations stay in `db/repositories/`; methods scope user-owned data.
  Application services own transactions. New code must not grow the compatibility
  facade in `db/repository.py` or introduce empty per-table wrappers.
- Supplied `Settings`, session URLs, provider approvals and usage writes target the
  same install. Check helper calls and error paths for global-setting fallbacks.
- Models and Alembic agree, including indexes. Only the backup-first upgrade runner
  changes schema; startup refuses old versions without `create_all` or fallback DDL.
- Preserve body-scan tables, legacy user fields, unrelated DBs and stored payloads.
  Verify preservation with populated fixtures, not empty-table assertions.

### Decisions, Plans and AI

- Daily intensity/ranking and shared weekly-load rules remain code-owned in
  `coach/decision.py`, `coach/load_model.py` and `coach/week_rules.py`.
  Read paths must not import proposal generation just to calculate a metric.
- The same usual-week definition and load scale reach Today, Insights, planning
  and worker messages. Check as-of dates, missing days, walking and excluded sports.
- Apply validates the exact accepted set before writes, enforces dependency groups,
  rejects stale versions and saves an undo snapshot. Check fixed commitments,
  protected habits, structured workout texts and unrelated athlete edits.
- Opinions keep code-owned intent/data notes and code-built evidence. Check the
  reusable verifier with signs, units, rounding and unsupported numbers. Repeated
  failure keeps the old review; regeneration archives it transactionally.
- Locks, daily call accounting and repair limits cover each active entry point.
  Compatibility CLI paths must use the current guarded application workflows.
- Imported names, notes, timeline entries and memories remain untrusted context.
  Suggested memories are not active until kept; planner restrictions are code rules.
- Remote sharing needs explicit config approval. Never make live provider calls
  during a review without separate task authorization.

### Web, Imports and Worker

- FastAPI routes are thin; view models shape presentation. HTMX mutations preserve
  authorization, validation, loading/errors and no-JS behavior. Test real routes.
- Check missing versus inapplicable values, stored km/min units, v2 wording, phone
  overflow, chart labels and keyboard access. Inspect Google map data disclosure
  when GPS or map configuration changes.
- Garmin normalization preserves IDs, units, laps, streams and user notes. CSV
  continues to work; no FIT support claim without an implemented path and tests.
- Worker jobs use local dates, a single-worker lock, durable claims and honest
  uncertain-send handling. Quiet hours, allowlists, token redaction and backup
  retention/restore protections must survive errors and restarts.
- Performance claims need profiles or query-plan/read-count evidence. Scoped
  calculation reuse must isolate users/settings and refresh on the next render.

### Public Release

Read `docs/release.md` when publication or packaging is in scope.
- Check both the tracked tree and relevant Git history. Deleted/ignored personal
  health files may remain in commits even when Gitleaks reports no secrets.
  Do not print private row contents, tokens or athlete values in a report.
- Inspect built wheel/source contents for private artifacts and required runtime
  modules, templates, fonts, JS, migrations and sample data. Checkout tests can hide
  missing packages; use `scripts/check_distribution.py` outside the checkout.
- Compare README, agent guidance and operational docs to actual startup/migration
  behavior. Mark superseded ADRs and distinguish historical milestones from current rules.
- Identify a Git authentication/workflow-permission failure as such; do not remove
  CI or rewrite history as a workaround. Publishing and force-pushing need approval.

## Verification and Findings

Run relevant focused tests and the full required suite when feasible; report
exactly what ran, warnings/failures, and important untested paths. Mock external
providers and use disposable databases. Browser and live-provider checks are
separate from unit tests. A green suite or static boundary scan is not proof of
all behavior or dependency direction.

Lead with findings ordered by severity. Each finding needs a file/line reference,
a concrete failure scenario, impact and a minimal corrective direction. Separate
confirmed defects from assumptions or optional improvements. Then give open
questions, a brief architecture assessment when requested, and verification results.

For architecture recommendations, identify the existing owner, misplaced behavior,
proposed boundary, testability benefit and migration risk. Prefer fewer places to
change a rule over more layers. Do not start the refactor during a review.

If no actionable issue is found, say so and name the residual test/verification gap.
