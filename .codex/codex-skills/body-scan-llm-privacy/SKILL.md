---
name: scan-insight-privacy
description: Keep Running Coach body scan LLM insights private, conservative, and schema-aligned. Use when Codex is asked to edit services/body_scan_insight_service.py, body scan insight prompts, LLM context construction, scan insight history, BodyScanInsightSchema, or tests that verify runtime/debug paths are not sent to the LLM.
---

# Scan Insight Privacy

## Start Here

Read `.codex/agent.md` first. Inspect current files before editing:

- `services/body_scan_insight_service.py`
- `services/llm_workflow.py`
- `llm/schemas.py`
- `app/pages/9_Body_Progress.py`
- `body_progress/mesh_analysis.py`
- `body_progress/sam3d_processor.py`
- `tests/test_body_progress.py`

## Privacy Boundary

Send only coaching-relevant scan context to the LLM:

- scan date, view, status, notes
- processor name
- pose quality and posture metrics
- SAM shape metrics such as height/width/depth proxies, ratios, balance, vertex/face counts
- prior insight summaries and coaching actions
- athlete focus question

Never send runtime/debug/local machine data to LLM prompts:

- `command`
- `checkpoint_path`
- `mhr_path`
- `repo_dir`
- `output_dir`
- `metadata_path`
- `mesh_path`
- `stdout_tail`
- `stderr_tail`
- raw image paths or local filesystem paths

Use `_compact_measurements()` and `_compact_shape_metrics()` as the main allowlist boundary. Keep structured model calls routed through `services/llm_workflow.py`.

## Prompt Rules

- Keep the coach conservative: no diagnosis, no body-fat estimates, no injury certainty from photos or meshes.
- Treat SAM metrics as relative tracking proxies.
- Ask the model to cite scan dates, views, metric names, and values when available.
- Keep prompt JSON keys aligned with `llm/schemas.py::BodyScanInsightSchema`.
- If accepting legacy or extra LLM keys, normalize them into the stored schema rather than expanding prompts accidentally.

## Tests

Add or update tests when changing prompt context or metric filtering. Include a regression test that path/debug fields are removed before prompt construction.

Run:

```bash
python -m ruff check services/body_scan_insight_service.py llm/schemas.py tests/test_body_progress.py
python -m pytest tests/test_body_progress.py
```

If `pytest` is unavailable, run `py_compile`, `ruff`, and a direct smoke check for `_compact_measurements()`.
