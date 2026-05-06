---
name: body-progress
description: Maintain the Marathon Coach Body Progress and SAM 3D Body workflow. Use when Codex is asked to change body scan uploads, BODY_SCAN_PROCESSOR=sam3d or mediapipe behavior, SAM checkpoint/MHR config, headless SAM execution, mesh metric extraction, scan cards, or the mesh-based avatar.
---

# Body Progress

## Start Here

Read `.codex/agent.md` first, then inspect the relevant current files before editing.

Core files:

- `app/pages/9_Body_Progress.py`
- `services/body_progress_service.py`
- `body_progress/sam3d_processor.py`
- `body_progress/sam3d_cli.py`
- `body_progress/mesh_analysis.py`
- `body_progress/mediapipe_processor.py`
- `tests/test_body_progress.py`

## SAM Configuration

The expected SAM 3D Body paths are:

```text
SAM3D_REPO_DIR=sam/sam-3d-body
SAM3D_CHECKPOINT_PATH=sam/sam-3d-body/checkpoints/sam-3d-body-dinov3/model.ckpt
SAM3D_MHR_PATH=sam/sam-3d-body/checkpoints/sam-3d-body-dinov3/assets/mhr_model.pt
SAM3D_OUTPUT_DIR=data/body_scan_outputs/sam3d
```

Use `BODY_SCAN_PROCESSOR=sam3d` for SAM and `BODY_SCAN_PROCESSOR=mediapipe` for the fast local fallback.

## Rules

- Prefer `scripts/run_sam3d_headless.sh` and `body_progress/sam3d_cli.py` for manual/headless SAM tests.
- Do not blindly overwrite local CPU/headless patches in `sam/sam-3d-body`.
- Treat SAM mesh metrics as relative coaching/tracking proxies only.
- Do not present mesh metrics as medical, diagnostic, body-fat, or exact anthropometric measurements.
- Store preview images, `.ply` mesh paths, metadata, and shape metrics locally through the processor contract.
- The Body Progress page should show understandable scan metrics and use the mesh-based avatar when `shape_metrics` exist.

## Metric Work

Mesh metrics live in `body_progress/mesh_analysis.py`.

Allowed coaching metrics include:

- height/width/depth proxies
- width/depth ratios
- left/right and front/back balance
- upper/lower vertex ratios
- vertex/face counts
- keypoint-derived shoulder/hip/torso proxy metrics

Keep filesystem paths and debug data out of user-facing metrics unless the user explicitly asks for local debugging output.

## Checks

Run targeted checks after edits:

```bash
python -m ruff check app/pages/9_Body_Progress.py services/body_progress_service.py body_progress/sam3d_processor.py body_progress/sam3d_cli.py body_progress/mesh_analysis.py tests/test_body_progress.py
python -m pytest tests/test_body_progress.py
```

For manual SAM verification:

```bash
scripts/run_sam3d_headless.sh /full/path/to/body-photo.jpg
```
