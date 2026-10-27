# Milestone 5e-1: UI v2 shell and Today

## Scope and files

- Updated `AGENTS.md` and `docs/PLAN.md` with the v2 decision and four 5e steps.
- Replaced the shared shell in `web/templates/base.html`; adjusted `web/templates/login.html` so sign-in remains outside the app shell.
- Replaced `web/templates/today.html` and added `web/templates/components/v2_today_call.html` and `v2_coach_answer.html`.
- Added `web/static/css/v2.css`, `web/static/js/v2.js` and pure shaping in `web/view_models/today.py`; wired it through `web/today.py` and `web/routes/pages.py`.
- Updated `tests/test_navigation.py`, `tests/test_web_today.py`; added `tests/test_web_v2_today.py`.

## Run and verify

Run `python -m web` against an upgraded database, then open `/`. At phone width, Ask opens the coach sheet; at tablet width, Ask opens the slide-over; from 1200 px the panel is docked. Submit a question to test the existing coach endpoint. The page render itself uses a null LLM client, so no LLM request is made until a question is submitted. The decision override still writes only `athlete_choice`.

Private screenshots are in `docs/private/screenshots/5e-1/`: night at 390, 1024 and 1440 px; phone Ask sheet; and a 390 px day-theme check. They are git-ignored and are not part of this report.

## Validation

- Ruff: pass.
- Compileall: pass.
- Full pytest: 536 passed, one existing SQLAlchemy row-count warning.
- Browser: HTTP 200 at all three widths, three dials rendered, no horizontal overflow; phone sheet opens; day-theme cookie works.

## Gaps and differences

- The metrics engine has no dated baseline for readiness itself. Recovery therefore has no invented "usual readiness" number; Sleep uses its 28-day baseline, and Load compares acute to the chronic weekly load.
- Ordinary `plan_sessions` do not contain structured workout steps. Those sessions show their duration only; a code-recommended session can show its existing structure as text. No synthetic workout profile is drawn.
- The old Today recovery tiles, load chart and recent-activity table are not in the v2 Today reference; their data remains available through Insights and Activities.
- The full decision explanation remains in the coach panel; the Today card shows its first sentence to keep the phone layout compact. The real wording can still make the week strip scroll beneath the fixed tab bar on a small screen.
- Non-Today pages retain their existing content and CSS inside the new shell until 5e-2 through 5e-4.
