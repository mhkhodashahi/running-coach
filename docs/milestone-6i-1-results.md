# Milestone 6i-1 Results

## Delivered

- Insights retains the Overview page and adds **My dashboard** at `/insights/dashboard`.
- The chart library contains planned vs done, intensity share, best efforts, easy pace vs HR, sleep vs Recovery, weekly load, training mix, and Recovery trends. All chart values come from stored activities, plans, health, existing metrics, sport mapping, intent rules, and the usual-week helper. No LLM runs on render.
- Four default charts render without a write. Add, edit, duplicate, reorder, and remove save the whole ordered set. Options are validated; the editor previews changes with HTMX. The same rows back SVG, table, and CSV. An empty saved dashboard stays empty.
- Migration `0014_dashboard_widgets` adds only `dashboard_widgets` and its user index. Its downgrade drops only that table. Upgrade/downgrade and preservation were tested on temporary databases. The commands run for this task upgraded only `/tmp` copies. A later read-only check found the working database already at `0014_dashboard_widgets`, with a backup in `db/backups/`; the upgrade happened outside this task's commands.

## Files

- `docs/PLAN.md`; `db/models.py`; `db/migrations/versions/0014_dashboard_widgets.py`; `tests/test_migrations.py`; `tests/test_web_dashboard.py`.
- `web/dashboard/__init__.py`, `charts.py`, `page.py`, `storage.py`; `web/view_models/dashboard.py`; `web/charts.py`; `web/routes/pages.py`.
- `web/templates/dashboard.html`, `components/dashboard_preview.html`, `trends.html`, `base.html`, `components/v2_icons.html`; `web/static/css/v2.css`, `web/static/js/v2.js`.

## Verify

1. Stop the web app and worker, then run `python -m scripts.upgrade_db --db db/running_coach.db`. The runner creates a backup first. Start with `python -m web` and open `/insights/dashboard`.
2. Confirm four charts appear on first visit, with no `dashboard_widgets` rows until an explicit edit. Add a chart, change its options, reorder it, export CSV, and compare it to **Show as table**.
3. Private screenshots are in `docs/private/screenshots/6i-1/`: 1440/390 night, 1440 day, chart library, edit preview, and an empty-data widget. They were captured on a fresh upgraded disposable copy. The 390 px page had no horizontal overflow.

## Checks

- `ruff check .`: PASS.
- `python -m compileall -q .`: PASS.
- Disposable-copy upgrade: `0014_dashboard_widgets`; integrity `ok`; existing activity, opinion, user and body-scan table counts preserved.
- Full `pytest -q`: 656 passed, 2 failed, 1 warning. Both failures are pre-existing assertions in `tests/test_coaching_prompts.py` expecting the phrase `evidence-led endurance coach` in unrelated prompts. The dashboard and migration tests pass. The local price configuration required temporary non-secret numeric overrides for test collection; `.env` was not edited.

## Gaps

- Zone-share and easy-intent charts omit sessions without an HR stream; they do not invent time in zones. Best-effort charts use only sample windows, full-km laps, or qualifying whole activities; otherwise they show a no-data state.
- A usual range band is hidden when the preceding equal-length period lacks enough health days. Weekly load weeks with fewer than four prior training weeks are muted and labelled as a baseline still building, not assigned an invented percentage.
- Chart options are limited to the registry's specified controls. No new metrics, coach logic, schema backfill, or 6i-2 work was added.
