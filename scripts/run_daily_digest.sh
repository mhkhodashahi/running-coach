#!/bin/bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

if [ ! -x "$PROJECT_DIR/.venv/bin/python" ]; then
  echo "Missing virtualenv interpreter at $PROJECT_DIR/.venv/bin/python" >&2
  exit 1
fi

mkdir -p "$PROJECT_DIR/logs"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting daily coaching digest"
"$PROJECT_DIR/.venv/bin/python" -m utils.daily_digest_cli --decision-type daily --send-telegram
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Daily coaching digest finished"
