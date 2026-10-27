# Milestone 5e-1b: UI v2 review fixes

## Changes

- `web/view_models/today.py`, `web/today.py`: consistent Recovery and Load display wording, code-built call headline and purpose, fact-based coach chips, full decision text normalized only for web display, and multi-item week days. Today's timestamped activities now appear in the read-only view query.
- `web/templates/base.html`, `web/templates/today.html`, `web/templates/components/v2_today_call.html`, `web/templates/components/v2_icons.html`, `web/templates/trends.html`: reference-style inline SVG icons; simplified rail; Activity and full chat links remain accessible; Today can show a completed activity beside an outstanding session.
- `web/static/css/v2.css`: tablet-only Ask trigger, desktop docked-panel behavior, day-theme Recovery stroke, and phone safe-area/tab-bar clearance.
- `tests/test_web_v2_today.py`, `tests/test_web_today.py`, `tests/test_navigation.py`: new presentation contract and route regression coverage.

## Verification

Run `python -m web` against an upgraded database. Check Today at phone, tablet and desktop widths; open Ask on phone/tablet; follow the full-chat and all-activities links. The screenshots are private and git-ignored in `docs/private/screenshots/5e-1b/`.

- Ruff: pass. Compileall: pass. Full pytest: 540 passed; one existing SQLAlchemy row-count warning.
- Browser: Today at 390x844 (top and scrolled bottom), 375x667 (scrolled bottom), 1024x768, 1440x960; phone Ask sheet; day theme at 390 and 1440.
- Browser geometry: Today, Training, Insights, Activity, Coach and Settings all returned 200, had no horizontal overflow, and their final main element cleared the fixed tab bar at both phone sizes when scrolled to the end.
- Day theme: computed Recovery ring stroke matched `--volt-ink`; Sleep and Load marks remained visible. At desktop width the tablet-only Ask rail button and Today's "Why this?" button were hidden.

## Remaining limits

- The plan schema has no dedicated purpose field. When no explicit purpose is supplied, the call card uses only a plain sentence from the existing dial statuses; free-form plan notes are not assumed to be a purpose.
- The web-only decision wording normalizer covers the stored code explanations and tested forms of the ratio and Recovery wording. The stored decision, metric names, Telegram copy and rules are unchanged.
