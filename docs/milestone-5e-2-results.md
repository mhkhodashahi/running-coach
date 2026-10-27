# Milestone 5e-2 results

## Scope

Training now uses the v2 shell: a dated week grid on web and day rows on phones, a weekly done/planned load bar, recurring-training links, and proposal review. Existing plan editors, approval, revision, stale check, and undo remain in place. The Training coach panel uses deterministic week facts; it does not call an LLM while rendering.

The carry-over fixes update the shared decision copy, Sleep dial wording, Today phone week strip, and coach-sheet focus behavior.

## Files changed

- `services/daily_decision_service.py`: shared 48-hour wording.
- `web/view_models/today.py`, `web/templates/today.html`, `web/templates/base.html`: dial, week-strip, and coach focus presentation.
- `web/view_models/training.py`, `web/plan_page.py`, `web/routes/pages.py`: pure Training presentation models and thin preview/chat routes.
- `web/templates/plan.html`, `web/templates/components/v2_training_week.html`, `v2_proposal.html`, `v2_proposal_banner.html`, `v2_proposal_preview.html`: Training and proposal markup.
- `web/static/css/v2.css`, `web/static/js/v2.js`: responsive layout, sheet handling, group checkbox synchronization, and HTMX preview updates.
- `tests/test_web_v2_training.py`, `tests/test_web_v2_today.py`, `tests/test_web_today.py`: invented-data view-model and route coverage.

## Verification

Run `python -m web`, open `/plan`, and inspect the week, proposal review, and coach panel at phone, tablet, and desktop widths. A proposed change can be unchecked without applying it; linked changes move together. The load preview and Apply count update. Without JavaScript, the form posts normally and the server still rejects partial groups. A stale proposal has no Apply action.

Private screenshots are in `docs/private/screenshots/5e-2/` for the requested night/day, phone/tablet/desktop, proposal, stale, and Today states. The screenshot database was a disposable copy; no working database was upgraded or edited.

Ruff, compileall, and the full pytest suite passed. The suite emitted one pre-existing SQLAlchemy warning in a nutrition repository test.
The browser console also reported a missing favicon request (404); it did not affect the page or interactions.

## Gaps and differences

- The Month control shows a rolling four-week view because there was no existing calendar-month view to restyle. It uses the same week data, not a new metric.
- The design's example proposal copy and numbers were not copied. Proposal text and load come from the saved proposal and existing load reference; missing reference data is shown as No data with sync time.
- A real workout profile is not stored for every planned session, so Training shows its available duration and HR cap and omits steps where absent.
- The existing plan editors remain below the week rather than being rebuilt in this milestone, preserving their current actions.
