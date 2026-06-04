#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# run.sh  –  convenient wrapper for organizer.py
#
# Usage examples:
#   ./run.sh -s ~/Photos/Raw -d ~/Photos/Organized
#   ./run.sh -s /mnt/camera -d ~/Organized --duplicates ~/Dupes -t 20
#   ./run.sh --help
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"
APP="$SCRIPT_DIR/organizer.py"

# ── Sanity checks ─────────────────────────────────────────────────────────────
if ! command -v "$PYTHON" &>/dev/null; then
  echo "ERROR: '$PYTHON' not found. Set the PYTHON env var to point to Python 3.9+." >&2
  exit 1
fi

PY_VERSION=$("$PYTHON" -c "import sys; print(sys.version_info >= (3,9))")
if [[ "$PY_VERSION" != "True" ]]; then
  echo "ERROR: Python 3.9 or newer is required." >&2
  exit 1
fi

if [[ ! -f "$APP" ]]; then
  echo "ERROR: organizer.py not found at $APP" >&2
  exit 1
fi

# ── Show help if no arguments ────────────────────────────────────────────────
if [[ $# -eq 0 ]]; then
  echo ""
  echo "  File Organizer"
  echo "  ─────────────────────────────────────────────────────────────────"
  echo "  Moves files from SOURCE to DESTINATION organized by date."
  echo "  Duplicates are detected by content hash and moved separately."
  echo ""
  echo "  Required:"
  echo "    -s, --source        <path>   Directory to scan"
  echo "    -d, --destination   <path>   Root output directory"
  echo ""
  echo "  Optional:"
  echo "    --duplicates        <path>   Directory for duplicate files"
  echo "    -t, --threads       <int>    Worker threads (default: 10)"
  echo "    -v, --verbose                Enable debug logging"
  echo "    -h, --help                   Show this help"
  echo ""
  echo "  Output structure:"
  echo "    <destination>/"
  echo "      2024/"
  echo "        06-June/"
  echo "          15/"
  echo "            photo.jpg"
  echo "            document.pdf"
  echo ""
  echo "  Examples:"
  echo "    ./run.sh -s ~/Downloads -d ~/Organized"
  echo "    ./run.sh -s ~/Downloads -d ~/Organized --duplicates ~/Dupes -t 20 -v"
  echo ""
  exit 0
fi

# ── Run ───────────────────────────────────────────────────────────────────────
exec "$PYTHON" "$APP" "$@"
