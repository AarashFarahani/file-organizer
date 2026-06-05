#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# run.sh  –  wrapper for the File Organizer Toolkit
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" &>/dev/null; then
  echo "ERROR: '$PYTHON' not found. Set PYTHON env var to point to Python 3.9+." >&2
  exit 1
fi

PY_VERSION=$("$PYTHON" -c "import sys; print(sys.version_info >= (3,9))")
if [[ "$PY_VERSION" != "True" ]]; then
  echo "ERROR: Python 3.9 or newer is required." >&2
  exit 1
fi

exec "$PYTHON" "$SCRIPT_DIR/main.py" "$@"
