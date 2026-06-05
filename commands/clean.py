"""
clean command — delete empty directories (including dirs with only empty subdirs).
"""

import logging
import argparse
from pathlib import Path

from commands.base import BaseCommand

log = logging.getLogger(__name__)


class CleanCommand(BaseCommand):

    def build_parser(self) -> argparse.ArgumentParser:
        p = argparse.ArgumentParser(
            prog="organizer clean",
            description=(
                "Delete empty directories recursively. "
                "A directory is considered empty if it contains no files "
                "anywhere in its subtree (nested empty subdirs don't count)."
            ),
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        )
        p.add_argument("target", help="Root directory to clean.")
        p.add_argument("--dry-run", action="store_true",
                       help="Show what would be deleted without removing anything.")
        p.add_argument("-v", "--verbose", action="store_true",
                       help="Also log directories that are kept.")
        return p

    def execute(self, args) -> None:
        target = Path(args.target).resolve()

        if not target.exists():
            log.error("Directory does not exist: %s", target)
            raise SystemExit(1)
        if not target.is_dir():
            log.error("Not a directory: %s", target)
            raise SystemExit(1)

        mode = "DRY-RUN" if args.dry_run else "LIVE"
        log.info("Scanning %s  [%s]", target, mode)

        removed, skipped = self._clean(target, dry_run=args.dry_run)
        log.info("Done.  Removed: %d  |  Skipped: %d", removed, skipped)

    # ── Internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _is_empty_tree(path: Path) -> bool:
        """True if the entire subtree contains zero files."""
        for entry in path.rglob("*"):
            if entry.is_file():
                return False
        return True

    def _clean(self, root: Path, dry_run: bool) -> tuple:
        removed = 0
        skipped = 0

        # Sort deepest-first so children are removed before parents
        dirs = sorted(
            (p for p in root.rglob("*") if p.is_dir()),
            key=lambda p: len(p.parts),
            reverse=True,
        )

        for dirpath in dirs:
            if not self._is_empty_tree(dirpath):
                log.debug("KEPT     %s  (contains files)", dirpath)
                continue

            if dry_run:
                log.info("DRY-RUN  would remove: %s", dirpath)
                removed += 1
            else:
                try:
                    dirpath.rmdir()
                    log.info("REMOVED  %s", dirpath)
                    removed += 1
                except OSError as exc:
                    log.warning("SKIPPED  %s  (%s)", dirpath, exc)
                    skipped += 1

        return removed, skipped
