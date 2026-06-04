#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# run.sh  –  convenient wrapper for organizer.py and clean_empty_dirs.py
#
# Usage examples:
#   ./run.sh organize -s ~/Photos/Raw -d ~/Photos/Organized
#   ./run.sh organize -s /mnt/camera -d ~/Organized --duplicates ~/Dupes -t 20
#   ./run.sh clean ~/Photos/Organized
#   ./run.sh clean --dry-run ~/Photos/Organized
#   ./run.sh --help
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"

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

# ── Help ──────────────────────────────────────────────────────────────────────
print_help() {
  echo ""
  echo "  File Organizer Toolkit"
  echo "  ─────────────────────────────────────────────────────────────────"
  echo ""
  echo "  COMMANDS:"
  echo ""
  echo "    organize   Move files into year/month folders by creation date"
  echo "    clean      Delete empty directories (including empty subtrees)"
  echo ""
  echo "  ── organize ──────────────────────────────────────────────────────"
  echo "  Required:"
  echo "    -s, --source        <path>   Directory to scan"
  echo "    -d, --destination   <path>   Root output directory"
  echo ""
  echo "  Optional:"
  echo "    --duplicates        <path>   Directory for duplicate files"
  echo "    -t, --threads       <int>    Worker threads (default: 10)"
  echo "    -v, --verbose                Enable debug logging"
  echo ""
  echo "  ── clean ─────────────────────────────────────────────────────────"
  echo "  Required:"
  echo "    <path>                       Directory to clean"
  echo ""
  echo "  Optional:"
  echo "    --dry-run                    Preview deletions without removing"
  echo "    -v, --verbose                Show kept directories too"
  echo ""
  echo "  EXAMPLES:"
  echo "    ./run.sh organize -s ~/Downloads -d ~/Organized"
  echo "    ./run.sh organize -s ~/Downloads -d ~/Organized --duplicates ~/Dupes -t 20"
  echo "    ./run.sh clean ~/Organized"
  echo "    ./run.sh clean --dry-run ~/Organized"
  echo ""
}

# ── Dispatch ──────────────────────────────────────────────────────────────────
COMMAND="${1:-}"

case "$COMMAND" in
  organize)
    shift
    exec "$PYTHON" "$SCRIPT_DIR/organizer.py" "$@"
    ;;
  clean)
    shift
    exec "$PYTHON" "$SCRIPT_DIR/clean_empty_dirs.py" "$@"
    ;;
  --help|-h|help|"")
    print_help
    exit 0
    ;;
  *)
    echo "ERROR: Unknown command '$COMMAND'. Use 'organize' or 'clean'." >&2
    print_help
    exit 1
    ;;
esac
