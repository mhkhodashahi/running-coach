# Milestone 6i-2 Results

## Scope and files

- Overview-to-dashboard: `web/dashboard/page.py`, `web/dashboard/storage.py`, `web/routes/pages.py`, `web/templates/trends.html`.
- Timeline notes: `db/migrations/versions/0015_timeline_notes.py`, `db/models.py`, `services/timeline_notes.py`, `web/charts.py`, `web/view_models/insights.py`, `web/trends.py`, `web/today.py`, `web/templates/today.html`, `web/templates/dashboard.html`, `web/templates/components/timeline_notes.html`, `web/templates/components/dashboard_preview.html`.
- Coach context: `coach/tools.py`, `coach/agent.py`, `services/daily_decision_service.py`, `web/view_models/dashboard.py`, `web/templates/components/dashboard_coach_context.html`, `web/templates/base.html`.
- Chart options and styles: `web/dashboard/charts.py`, `web/static/css/v2.css`.
- Rules and tests: `AGENTS.md`, `docs/PLAN.md`, `tests/test_dashboard_6i2.py`, `tests/test_web_dashboard.py`, `tests/test_migrations.py`.

## Behavior

- An Overview card adds the matching widget with its selected range. A widget with the same chart and full validated options is reported as already present.
- Notes are user-scoped, limited to 200 characters, editable and deletable with confirmation. They appear as dated chart markers, in a list below the chart, and in the table and CSV. A note-only period keeps an accessible table without drawing empty axes.
- Notes from the preceding 14 days enter daily and chat fact packs as escaped, labelled **untrusted athlete data**. They use the existing provider approval and coach-call limit. The chat and daily prompt versions are `chat-v1.4` and `daily-v2.4`; stored history is unchanged.
- “Ask the coach” opens the existing panel with a deterministic chart summary and title context. Opening it makes no model call. Sending a question uses the existing chat service and approval policy.
- The recovery daily time series supports the usual band and 7-day moving average, both on by default and individually switchable. Weekly and scatter charts do not offer a day-to-day usual band because that comparison is not defined for those chart types.

## Verification

- Revision: `0015_timeline_notes`, additive and backup-first via `python -m scripts.upgrade_db --db <copy>`. Upgrade and downgrade were tested on temporary databases, with existing user and widget rows preserved and SQLite integrity `ok`. This task's upgrade command targeted only a temporary copy. A read-only check found the working database at `0014_dashboard_widgets` before verification and `0015_timeline_notes` at the end, with a new backup in `db/backups/`. The cause of that concurrent change was not verified.
- `ruff check .`: PASS.
- `python -m compileall -q .`: PASS.
- Focused dashboard/migration tests: 53 passed.
- Full `pytest -q`: 668 passed, 2 failed, 1 warning. The failures are pre-existing `tests/test_coaching_prompts.py` assertions for the retired phrase `evidence-led endurance coach`; they were also recorded in 6i-1. The SQLAlchemy nutrition deletion warning is unrelated.
- Private browser captures: `docs/private/screenshots/6i-2/` (dashboard at desktop and phone, Overview card menu, add-note sheet, chart coach context). Captures use a disposable upgraded database copy and are git-ignored.

## Gaps

- A note on a period with no metric data is listed in the accessible table and note list, but no empty chart axes are drawn, by design.
- The general coach can cite timeline-note facts; it does not receive a separate chart-data tool in this milestone. The chart summary is supplied as context when a chart question is sent, and existing tool and fact validation still governs the answer.
