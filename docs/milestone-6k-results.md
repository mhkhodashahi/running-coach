# Milestone 6k: Detailed plan suggestions

## Delivered

- Migration `0017_detailed_workouts` adds nullable `workout_type` and `workout_json` to plan sessions and proposal changes. Existing plans stay valid without structured steps. The backup-first runner upgraded a disposable copy; the working database was not upgraded.
- `coach/workouts.py` defines ten templates: running recovery, easy/base, long, tempo, threshold, VO2 max intervals and speed; gym strength for runners and upper body/core; and mobility. Each includes purpose, benefit, warm-up/main/cool-down steps where applicable, effort, shorter/longer variants, and a progression rule. Gym templates specify exercises and rounds without weights.
- Targets come from configured HR zones and recent observed pace in the relevant zone. Sparse pace data omits pace targets. Race paces come from recorded best efforts or the active goal. The existing load estimator supplies the session estimate.
- The week builder derives base/build/sharpen/taper or maintenance from the active goal. It limits quality runs, separates hard days, keeps a long run within the existing cap, protects fixed team commitments, and respects the weekly load limit. When the running goal needs room, it can propose dropping flexible light gym work; it never applies the change without approval. Proposal summaries include phase, focus, key session and available progression comparisons.
- The LLM writes explanation only, not workouts. The 6h number verifier checks its summary and reasons. One repair retry is allowed; another failure uses the code-written version. Proposal review expands every structured workout; Training shows its type; Today shows saved steps. Approval and undo preserve the structured fields.

## Files

Added: `coach/workouts.py`, `db/migrations/versions/0017_detailed_workouts.py`, `web/templates/components/v2_workout_detail.html`, `tests/test_workouts.py`, this report.

Changed: `docs/PLAN.md`, `coach/planning.py`, `coach/proposals.py`, `db/models.py`, `web/view_models/today.py`, `web/view_models/training.py`, `web/templates/components/v2_proposal.html`, `web/templates/components/v2_today_call.html`, `web/templates/components/v2_training_week.html`, `web/static/css/v2.css`, `tests/test_migrations.py`, `tests/test_morning_brief.py`, `tests/test_web_v2_today.py`, `tests/test_weekly_plan.py`.

## Verification

- `ruff check .`: pass.
- `python -m compileall -q coach db web tests`: pass.
- `pytest -q`: 727 passed, one existing SQLAlchemy warning in the nutrition repository test.
- Disposable database copy: backup-first upgrade reached `0017_detailed_workouts`; integrity check passed and observed table counts and opinion payloads were preserved. The copy had pre-existing foreign-key findings, unchanged by the migration. No production data was changed.
- The approved configured provider generated a proposal on a fresh disposable copy. Full private output is in `~/pulse-handoff-6k.md` (mode 0600); no athlete values are in this report. The final presentation-only refinement to step durations and the proposal title was not sent to the provider again.
- Private screenshots: `docs/private/screenshots/6k/proposal-1440.png`, `proposal-390.png`, and `training-next-1440.png`.

## Gaps

- HR-zone pace requires enough recent laps with usable HR. Otherwise the workout uses HR and effort targets only.
- Historic plan sessions have no structured workout until changed or replaced by an approved proposal.
- Conservative hard-day spacing uses calendar dates when exact session start times are unavailable.

## How to verify

Run `python -m scripts.upgrade_db --db <disposable-copy.db>`, start `python -m web` with `DB_PATH` pointing to that copy, then create a next-week proposal from Training. Expand a workout, apply it, check the Training type badge and Today steps, then undo and confirm the prior plan returns. The working database still requires the backup-first upgrade before this code can run against it.
