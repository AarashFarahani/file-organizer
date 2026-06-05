"""
delete command — delete all files whose names start with a given prefix.
Default prefix is '._' (macOS metadata/resource fork leftovers).
Runs multithreaded.
"""

import logging
import argparse
import threading
from pathlib import Path
from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed

from commands.base import BaseCommand

log = logging.getLogger(__name__)


class DeletePrefixedCommand(BaseCommand):

    def build_parser(self) -> argparse.ArgumentParser:
        p = argparse.ArgumentParser(
            prog="organizer delete",
            description=(
                "Delete files whose names start with a given prefix. "
                "Scans the target directory recursively. "
                "Default prefix is '._' (macOS resource-fork / metadata files)."
            ),
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        )
        p.add_argument("target", help="Directory to scan recursively.")
        p.add_argument(
            "--prefix",
            default="._",
            help="Delete files whose names start with this prefix.",
        )
        p.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without removing anything.",
        )
        p.add_argument(
            "-t", "--threads",
            type=int,
            default=10,
            help="Thread-pool size.",
        )
        p.add_argument("-v", "--verbose", action="store_true",
                       help="Enable DEBUG logging.")
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
        log.info("Scanning %s for files prefixed '%s'  [%s]", target, args.prefix, mode)

        worker = _DeleteWorker(
            target=target,
            prefix=args.prefix,
            dry_run=args.dry_run,
        )
        worker.run(threads=args.threads)


# ── Worker ────────────────────────────────────────────────────────────────────

class _DeleteWorker:

    def __init__(self, target: Path, prefix: str, dry_run: bool):
        self.target  = target
        self.prefix  = prefix
        self.dry_run = dry_run

        self._lock   = threading.Lock()
        self.deleted = 0
        self.skipped = 0
        self.errors  = 0

    def _collect(self) -> List[Path]:
        files = [
            p for p in self.target.rglob("*")
            if p.is_file() and not p.is_symlink() and p.name.startswith(self.prefix)
        ]
        log.info("Found %d file(s) matching prefix '%s'", len(files), self.prefix)
        return files

    def _delete(self, path: Path) -> None:
        if self.dry_run:
            log.info("DRY-RUN  would delete: %s", path)
            with self._lock:
                self.deleted += 1
            return

        try:
            path.unlink()
            log.info("DELETED  %s", path)
            with self._lock:
                self.deleted += 1
        except PermissionError as exc:
            log.error("SKIP | permission denied | file=%s | reason=%s", path, exc)
            with self._lock:
                self.skipped += 1
        except FileNotFoundError:
            # Another thread may have removed it already — not an error
            log.debug("SKIP | already gone: %s", path)
            with self._lock:
                self.skipped += 1
        except Exception as exc:
            log.error("SKIP | cannot delete | file=%s | reason=%s", path, exc)
            with self._lock:
                self.errors += 1

    def run(self, threads: int = 10) -> None:
        files = self._collect()
        if not files:
            log.info("Nothing to delete.")
            return

        log.info("Starting with %d thread(s)…", threads)
        with ThreadPoolExecutor(max_workers=threads) as pool:
            futures = {pool.submit(self._delete, f): f for f in files}
            for future in as_completed(futures):
                future.result()

        log.info("Done.  Deleted: %d  |  Skipped: %d  |  Errors: %d",
                 self.deleted, self.skipped, self.errors)
