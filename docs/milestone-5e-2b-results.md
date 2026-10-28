# Milestone 5e-2b results

## Scope

- Shared one `week_day` presentation model between Today and Training. A logged session and an unplanned suggested session can both appear for today. Training's coach summary counts a suggested hard day without treating the suggestion as a planned session or adding its load to the plan.
- Training load shows a word and icon with the Today dial thresholds, plus a 110% safe-limit marker on a 0–130% scale. The coach summary omits zero-count chips, and follow-ups change with load state and proposal availability.
- Pending proposals render before stale proposals. Stale proposals are compact, expandable rows; phone review sheets size to content. Change deltas include `load`, and dismiss requires confirmation. `Not now` only closes the phone sheet.
- The four plan buttons are one keyboard-accessible `Suggest a plan` menu. Day tiles have unframed session rows; editable sessions are whole-row links to an inline form.

## Light gym investigation

The four sessions in the previous screenshot did **not** all come from the working plan. The Thursday, Friday and Sunday `plan_sessions` rows have `origin=coach` and were created together when an accepted revision of a weekly proposal was applied (`proposal_id=2`). `plan_sessions` has `origin`, not a `created_by` column. The stored proposal `created_at` is `2026-10-27T09:41:18`; the plan rows' stored `created_at` values are around `2026-10-27T10:29:25` (the database timestamps carry no timezone offset). There is no active gym row in `protected_habits`. The reference habit rule computed `[redacted]` gym sessions per recorded week, explaining the flexible gym suggestions. The Saturday row appeared only in the disposable screenshot database: `docs/private/screenshots/5e-2/setup_capture.py` explicitly added it with `manual_session`, which set `origin=athlete`; its stored `created_at` is `2026-10-27T19:21:38`. The working database has no Saturday plan row. This is screenshot-fixture provenance, not a habit-generation bug; no planning code or working data was changed.

## Files changed

- `web/view_models/today.py`, `web/view_models/training.py`, `web/plan_page.py`
- `web/templates/plan.html`, `web/templates/components/v2_training_week.html`, `web/templates/components/v2_proposal.html`, `web/templates/components/v2_stale_row.html`
- `web/static/css/v2.css`, `web/static/js/v2.js`
- `tests/test_web_v2_training.py`, `tests/test_web_5c.py`
- This report. Private screenshot setup/capture scripts and images under `docs/private/screenshots/5e-2b/` are ignored by Git.

## Verify

Run `python -m web`, open `/` and `/plan` for the same date, and compare today's done and suggested entries. On `/plan`, open `Suggest a plan`, review a pending proposal, close it with `Not now`, expand a stale row, and open a session editor by selecting its row. Screenshots are in `docs/private/screenshots/5e-2b/` at 390, 1024 and 1440 px, including night/day, a proposal sheet, stale row, open plan menu and paired Today/Training views.

`ruff check .`: PASS. `python -m compileall -q .`: PASS. `pytest -q`: 553 passed, 1 pre-existing SQLAlchemy warning.

## Gaps and differences

- Suggested sessions are not included in planned load, because they are not plan sessions. Their hard-day status is visible in the coach summary.
- The desktop proposal stays visible; `Not now` is a phone-sheet close action. This avoids hiding the only desktop review surface.
- The disposable screenshot fixture's proposal notification hook emitted a warning because Telegram delivery was unavailable; no screenshot used a real Telegram or LLM response.
