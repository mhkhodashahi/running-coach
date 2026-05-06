# Marathon Coach Agent Guide

Use these repository-specific instructions for Codex work in this project.

## Project Context

- Marathon Coach is a local Streamlit running-coach app backed by SQLite.
- It analyzes Garmin-style activities, health and recovery metrics, goals, coaching digests, body progress scans, and running performance.
- Main Streamlit navigation entry point: `app/main.py`
- Dashboard page: `app/dashboard.py`
- Streamlit pages: `app/pages/`
- Body Progress page: `app/pages/9_Body_Progress.py`
- Reusable body scan code: `body_progress/`
- Data access: `db/repository.py`, `db/session.py`, and SQLAlchemy models in `db/models.py`
- LLM providers: `llm/openai_client.py`, `llm/ollama_client.py`, selected by `llm/factory.py`
- Coaching and LLM workflows: `services/`
- UI helpers: `ui/components.py`; Plotly charts: `ui/charts.py`

## Skill Map

Prefer these skill names when invoking repo guidance:

- `$project-guide`: general Marathon Coach changes, debugging, setup, tests, and explanations.
- `$review-marathon`: code-review mode for diffs, PR-like changes, regressions, privacy leaks, and missing tests.
- `$body-progress`: Body Progress, scan uploads, MediaPipe, SAM 3D Body, mesh metrics, and avatar work.
- `$scan-insight-privacy`: body scan LLM insight prompts, schema alignment, prompt context filtering, and privacy checks.

## Development Rules

- Inspect the current files before editing. Do not rely on memory of the codebase.
- Keep changes scoped to the request and follow nearby patterns.
- Preserve existing Streamlit page naming and navigation conventions. `app/main.py` uses `st.navigation`.
- Prefer reusable services/modules over page-only logic when behavior is shared.
- Do not remove Garmin, goal, Telegram, activity-detail, body-progress, or LLM workflows unless explicitly requested.
- Avoid destructive database or git commands.
- The project currently does not use real DB migrations. If adding tables/columns, keep model/repository updates and lightweight `CREATE TABLE IF NOT EXISTS` fallback SQL consistent.
- Keep analytics explainable and deterministic unless the user explicitly asks for LLM behavior.
- Keep body/scan outputs privacy-aware. Do not send raw image paths, checkpoint paths, command logs, stdout/stderr tails, or local machine paths to LLM prompts unless explicitly requested.
- Treat SAM mesh metrics as relative coaching/tracking proxies only. Do not present them as medical, diagnostic, body-fat, or exact anthropometric measurements.

## Body Progress And SAM

- The Body Progress page is gated by `.env`: set `use_sam=true` or `USE_SAM=true` to show it in navigation.
- Keep `app/pages/9_Body_Progress.py` behind `settings.use_sam`; direct access should stop when SAM mode is disabled.
- `BODY_SCAN_PROCESSOR=sam3d` runs the SAM 3D Body path.
- `BODY_SCAN_PROCESSOR=mediapipe` is the faster local pose-metrics fallback.
- SAM config is loaded from `.env`:
  - `SAM3D_REPO_DIR=sam/sam-3d-body`
  - `SAM3D_CHECKPOINT_PATH=sam/sam-3d-body/checkpoints/sam-3d-body-dinov3/model.ckpt`
  - `SAM3D_MHR_PATH=sam/sam-3d-body/checkpoints/sam-3d-body-dinov3/assets/mhr_model.pt`
  - `SAM3D_OUTPUT_DIR=data/body_scan_outputs/sam3d`
- Use `body_progress/sam3d_processor.py` for app integration.
- Use `body_progress/sam3d_cli.py` and `scripts/run_sam3d_headless.sh` for manual/headless SAM runs.
- Prefer the headless SAM runner over Meta's original `demo.py`; it avoids optional ViTDet/MoGe/SAM2 dependencies and macOS OpenGL rendering.
- If running Meta's `demo.py` manually, pass:

```bash
--detector_name "" --segmentor_name sam2 --fov_name ""
```

- Local SAM repo has CPU compatibility patches. Do not blindly overwrite them when updating the sub-repo.
- SAM output stores preview JPG, `.ply` mesh, metadata, and shape metrics.
- Mesh analysis lives in `body_progress/mesh_analysis.py`.

## LLM Scan Insights

- Body scan LLM insight workflow: `services/body_scan_insight_service.py`.
- LLM response schema: `llm/schemas.py` (`BodyScanInsightSchema`).
- Stored insight history table: `body_scan_insights`.
- The scan insight prompt should send only coaching-relevant data:
  - scan date/view/status/notes
  - processor name
  - pose quality and posture metrics
  - SAM shape metrics such as height/width/depth proxies, ratios, balance, vertex/face counts
  - prior insight summaries
  - athlete's focus question
- Do not send runtime/debug data to the LLM:
  - `command`
  - `checkpoint_path`
  - `mhr_path`
  - `repo_dir`
  - `output_dir`
  - `metadata_path`
  - `mesh_path`
  - `stdout_tail`
  - `stderr_tail`
  - local filesystem paths
- Keep prompts conservative: no diagnosis, no body-fat estimates, no injury certainty from photos/meshes.

## UX Preferences

- Keep the app style practical and motivational: warm orange accents, rounded cards, Plotly charts, and athlete-friendly labels.
- Dashboard and analysis pages should answer coaching questions, not just show raw data.
- Body Progress should make scan outputs understandable: preview image, scan metrics, SAM shape metrics, LLM insight history, and mesh-based avatar when available.
- Avoid unexplained model jargon in user-facing text.

## Verification

Run focused checks for touched files when practical.

For Python syntax:

```bash
python -m py_compile path/to/file.py
```

For linting:

```bash
python -m ruff check path/to/file.py
```

- For body progress changes, run:

```bash
python -m pytest tests/test_body_progress.py
```

- For broader changes, run:

```bash
python -m pytest
```

- Streamlit pages may emit `missing ScriptRunContext` warnings when executed outside `streamlit run`; those warnings are expected in bare smoke checks.
