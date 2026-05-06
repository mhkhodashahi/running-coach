#!/usr/bin/env bash
set -euo pipefail

IMAGE_PATH="${1:?Usage: scripts/run_sam3d_headless.sh /path/to/image [output_dir]}"
OUTPUT_DIR="${2:-data/body_scan_outputs/manual_sam3d}"

python -m body_progress.sam3d_cli \
  --repo_dir "${SAM3D_REPO_DIR:-sam/sam-3d-body}" \
  --image_path "$IMAGE_PATH" \
  --output_dir "$OUTPUT_DIR" \
  --checkpoint_path "${SAM3D_CHECKPOINT_PATH:-sam/sam-3d-body/checkpoints/sam-3d-body-dinov3/model.ckpt}" \
  --mhr_path "${SAM3D_MHR_PATH:-sam/sam-3d-body/checkpoints/sam-3d-body-dinov3/assets/mhr_model.pt}"
