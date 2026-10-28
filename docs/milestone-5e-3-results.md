# Milestone 5e-3 results

## Scope

Insights, Activity detail, and the Activities list now use the shared v2 shell. The Training and decision-copy carry-over fixes are included. Metrics, opinion payloads, plan rules, and the database schema were not changed. Insights and Activity page renders do not call an LLM.

## Files changed

- Decision wording: `services/daily_decision_service.py`.
- Pure presentation: `web/view_models/insights.py`, `web/view_models/activity.py`, `web/view_models/today.py`, `web/view_models/training.py`.
- Existing read paths and chart helpers: `web/trends.py`, `web/activities.py`, `web/plan_page.py`, `web/charts.py`, `web/routes/pages.py`.
- Templates: `web/templates/base.html`, `web/templates/trends.html`, `web/templates/activities.html`, `web/templates/activity_detail.html`, `web/templates/plan.html`, and the affected v2/activity components.
- Styling and interaction: `web/static/css/v2.css`, `web/static/js/v2.js`.
- Tests: `tests/test_daily_decision.py`, `tests/test_web_5c.py`, `tests/test_web_activities.py`, `tests/test_web_v2_training.py`, `tests/test_web_v2_insights_activity.py`.

## Verify

Run `python -m web` with a migrated database. Open `/trends?range=28`, `/activities`, a running activity, and `/plan`. The 7/28/90 controls retain their range in the URL. Activity tabs use anchors, so review, laps, and comparison remain reachable without JavaScript. The review is generated only by an explicit click. A legacy opinion is mapped for display and not rewritten.

Private screenshots are under `docs/private/screenshots/5e-3/` and are git-ignored. They cover phone, tablet, desktop, night/day Insights, missing-day ranges, v2/legacy/no-opinion Activity states, a gym session, the Activities list, and the Training carry-over. Playwright checked the sticky rail and panel, phone horizontal overflow, and Activity tab visibility against a disposable database copy.

## Tests

- `ruff check .`: pass.
- `python -m compileall -q .`: pass.
- `pytest -q`: 562 passed; one existing SQLAlchemy warning in the nutrition repository test.

## Gaps and differences

- The goal card is conditional on an active running goal. Without one, it is hidden rather than filled with example numbers.
- Charts leave gaps where health data is absent; a card with no usable value says "No data" and shows the last sync time. The sleep goal line appears only when a sleep goal is configured.
- The comparison tab appears only when the existing comparison tool finds sessions. The HR chart is hidden when samples are unavailable.
- The Activities list retains working sport/date/walk filters and pagination, so it is denser than the static design. The full review reuses the existing opinion controls, preserving explicit regeneration and add-to-plan proposal behavior. Old CSS remains for unfinished pages until 5e-4.
- The coach panel shows a deterministic summary and static follow-ups. Its input calls the existing chat endpoint only on submit.
