---
name: project-guide
description: Work safely and efficiently in the Running Coach Streamlit repository. Use when Codex is asked to modify, debug, or explain this project broadly, including dashboard pages, analytics, SQLite repository code, Garmin import/sync, LLM coaching services, tests, skills, or project setup.
---

# Project Guide

## Start Here

Read `.codex/agent.md` first. It is the persistent all-in-one project instruction file.

Use this skill for general Running Coach repo work. For Body Progress/SAM changes, use `$body-progress`. For scan insight prompts or privacy review, use `$scan-insight-privacy`. For review-only work, use `$review-running`.

## Repo Map

- Streamlit entry point: `app/main.py`
- Streamlit pages: `app/pages/`
- Body Progress page: `app/pages/9_Body_Progress.py`
- Body scan reusable package: `body_progress/`
- Garmin client/auth/sync orchestration: `services/garmin_client.py`
- Garmin payload and unit normalization: `services/garmin_normalization.py`
- Services and LLM workflows: `services/`
- Shared structured LLM call helper: `services/llm_workflow.py`
- LLM clients and schemas: `llm/`
- DB models/session/repository: `db/`
- UI helpers and charts: `ui/`
- Tests: `tests/`
- Domain glossary: `CONTEXT.md`
- Architecture decisions: `docs/adr/`

## Workflow

1. Inspect current files before editing; do not assume the code matches memory.
2. Prefer existing local patterns over new abstractions.
3. Keep edits scoped to the request.
4. Do not remove Garmin, goal, Telegram, activity-detail, body-progress, or LLM workflows unless explicitly requested.
5. Preserve privacy around body scan data; do not send raw local paths, command logs, or debug output to LLM prompts.
6. If adding SQLite tables or columns, update models/repository and centralized lightweight setup in `db/setup.py` consistently because this project does not use real migrations.
7. Keep Garmin field-shape and unit conversion rules in `services/garmin_normalization.py`; keep auth/API orchestration in `services/garmin_client.py`.
8. Route structured LLM calls through `services/llm_workflow.py` unless there is a concrete reason to bypass it.
9. The standalone Performance Dashboard page was removed. Do not re-add `app/pages/6_Analysis.py` or `app/performance_dashboard.html` unless explicitly requested.

## Checks

For touched Python files:

```bash
python -m py_compile path/to/file.py
python -m ruff check path/to/file.py
```

For Body Progress changes:

```bash
python -m pytest tests/test_body_progress.py
```

For wider changes:

```bash
python -m pytest
```

Streamlit pages can emit `missing ScriptRunContext` warnings outside `streamlit run`; those warnings are expected in bare smoke checks.

If `pytest` is unavailable in `.venv`, still run `py_compile`, `ruff`, and focused direct smoke checks for pure functions or page-free services.
