---
name: body-progress
description: Work on Running Coach Body Progress and scan processing. Use when Codex is asked to edit Body Progress Streamlit UI, scan uploads, MediaPipe, SAM 3D Body, Multi-HMR hooks, mesh analysis, body scan storage, avatar rendering, body scan LLM insights, scan prompt privacy, or body scan tests.
---

# Body Progress

## Start Here

Read `.codex/agent.md` first.

Inspect current files before editing:

- `app/pages/9_Body_Progress.py`
- `services/body_progress_service.py`
- `services/body_scan_insight_service.py` when insights are involved
- `services/llm_workflow.py` when structured LLM calls are involved
- `llm/schemas.py` when insight schema changes are involved
- `body_progress/`
- `db/repository.py`
- `db/setup.py`
- `tests/test_body_progress.py`

## Architecture Rules

- Body Progress navigation is gated by `settings.use_sam` in `app/main.py`.
- Keep table creation centralized in `db/setup.py`; pages and services should use `db.repository`.
- Use `BodyProgressService` for upload/storage/processing orchestration.
- Keep processor-specific code in `body_progress/*_processor.py`.
- Keep mesh metrics in `body_progress/mesh_analysis.py`.
- Treat SAM and mesh metrics as relative tracking proxies only.

## Privacy And Safety

- Do not send raw image paths, mesh paths, checkpoint paths, command logs, stdout/stderr tails, or local machine paths to LLM prompts.
- Do not present body scan output as medical diagnosis, exact anthropometry, injury certainty, or body-fat estimation.
- Respect `consent_to_store_image`; when false, source image storage must be removed and persisted scan rows must not expose the source path.
- Use `_compact_measurements()` and `_compact_shape_metrics()` as the scan insight prompt allowlist.
- Scan insight prompts may include scan date, view, status, notes, processor name, pose quality, posture metrics, SAM shape metrics, prior insight summaries, and athlete focus questions.
- Keep scan insight JSON keys aligned with `llm/schemas.py::BodyScanInsightSchema`.
- Route structured model calls through `services/llm_workflow.py`.

## Checks

Run focused checks for touched files:

```bash
python -m py_compile app/pages/9_Body_Progress.py services/body_progress_service.py services/body_scan_insight_service.py body_progress/processor.py
python -m ruff check app/pages/9_Body_Progress.py services/body_progress_service.py services/body_scan_insight_service.py body_progress llm/schemas.py tests/test_body_progress.py
python -m pytest tests/test_body_progress.py
```

If `pytest` is unavailable, run `py_compile`, `ruff`, and direct smoke checks for pure helper functions you changed, especially `_compact_measurements()` for prompt privacy.
