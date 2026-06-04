#!/usr/bin/env python3
"""
Empty Directory Cleaner
Recursively removes directories that are truly empty — including those
that contain only empty subdirectories (no files anywhere in the tree).
"""

import sys
import logging
import argparse
from pathlib import Path

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ── Core ──────────────────────────────────────────────────────────────────────

def is_empty_tree(path: Path) -> bool:
    """
    Return True if the directory contains zero files anywhere in its tree
    (it may contain subdirectories, but none of them have any files either).
    """
    for entry in path.rglob("*"):
        if entry.is_file():
            return False
    return True


def clean(root: Path, dry_run: bool = False) -> tuple:
    """
    Walk the tree bottom-up and remove every directory whose entire subtree
    contains no files. Returns (removed, skipped) counts.
    """
    removed = 0
    skipped = 0

    # bottom-up so children are processed before parents
    for dirpath in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if not dirpath.is_dir():
            continue

        if is_empty_tree(dirpath):
            if dry_run:
                log.info("DRY-RUN  would remove: %s", dirpath)
                removed += 1
            else:
                try:
                    # rmdir only works on truly empty dirs; we delete bottom-up
                    # so by the time we reach a parent all children are gone
                    dirpath.rmdir()
                    log.info("REMOVED  %s", dirpath)
                    removed += 1
                except OSError as exc:
                    log.warning("SKIPPED  %s  (%s)", dirpath, exc)
                    skipped += 1
        else:
            log.debug("KEPT     %s  (contains files)", dirpath)

    return removed, skipped


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Delete all empty directories (including those with only empty subdirectories).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "target",
        help="Root directory to clean.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting anything.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable DEBUG logging (shows kept directories too).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    target = Path(args.target).resolve()

    if not target.exists():
        log.error("Directory does not exist: %s", target)
        sys.exit(1)
    if not target.is_dir():
        log.error("Not a directory: %s", target)
        sys.exit(1)

    mode = "DRY-RUN" if args.dry_run else "LIVE"
    log.info("Scanning %s  [%s]", target, mode)

    removed, skipped = clean(target, dry_run=args.dry_run)

    log.info("Done.  Removed: %d  |  Skipped: %d", removed, skipped)


if __name__ == "__main__":
    main()
