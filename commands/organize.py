"""
organize command — move files into year/month folders by date.
"""

import logging
import argparse
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Set
from concurrent.futures import ThreadPoolExecutor, as_completed

from commands.base import BaseCommand
from commands.utils import (
    IS_MACOS,
    resolve_date,
    file_hash,
    safe_dest_path,
    move_file,
    set_file_dates,
)

log = logging.getLogger(__name__)


def _is_hidden(path: Path) -> bool:
    """
    Return True if any component of the path (relative to root) starts with a dot.
    Catches both hidden files (e.g. .DS_Store) and files inside hidden dirs (e.g. .git/config).
    """
    return any(part.startswith(".") for part in path.parts)


class OrganizeCommand(BaseCommand):

    def build_parser(self) -> argparse.ArgumentParser:
        p = argparse.ArgumentParser(
            prog="organizer organize",
            description="Move files into <destination>/YYYY/MM/ folders by date.",
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        )
        p.add_argument("-s", "--source", required=True,
                       help="Source directory to scan recursively.")
        p.add_argument("-d", "--destination", required=True,
                       help="Destination root directory.")
        p.add_argument("--duplicates", default=None,
                       help="Directory for duplicate files. Duplicates are skipped if omitted.")
        p.add_argument("-t", "--threads", type=int, default=10,
                       help="Thread-pool size.")
        p.add_argument("--use-filesystem-date", action="store_true", default=False,
                       help="Always use filesystem date. Default: try filename first.")
        p.add_argument("--no-update-dates", action="store_true", default=False,
                       help="Skip updating creation/modified dates after move.")
        p.add_argument("--include-hidden", action="store_true", default=False,
                       help="Include hidden files and files inside hidden directories. "
                            "Default: hidden files are skipped.")
        p.add_argument("-v", "--verbose", action="store_true",
                       help="Enable DEBUG logging.")
        return p

    def execute(self, args) -> None:
        source      = Path(args.source)
        destination = Path(args.destination)
        duplicates  = Path(args.duplicates) if args.duplicates else None

        if not source.exists() or not source.is_dir():
            log.error("Source must be an existing directory: %s", source)
            raise SystemExit(1)

        try:
            source.resolve().relative_to(destination.resolve())
            log.error("Source cannot be inside the destination directory.")
            raise SystemExit(1)
        except ValueError:
            pass

        destination.mkdir(parents=True, exist_ok=True)
        if duplicates:
            duplicates.mkdir(parents=True, exist_ok=True)

        prefer_filename = not args.use_filesystem_date
        update_dates    = not args.no_update_dates
        include_hidden  = args.include_hidden

        date_mode = "filename → filesystem fallback" if prefer_filename else "filesystem only"
        log.info("Date mode: %s", date_mode)
        log.info("Hidden files: %s", "included" if include_hidden else "skipped (use --include-hidden to change)")
        if update_dates:
            log.info("Date stamping: enabled (creation + modified)%s",
                     " [macOS]" if IS_MACOS else " [modified only — not macOS]")

        worker = _OrganizeWorker(
            source=source,
            destination=destination,
            duplicates=duplicates,
            prefer_filename_date=prefer_filename,
            update_dates=update_dates,
            include_hidden=include_hidden,
        )
        worker.run(threads=args.threads)


# ── Worker (holds all mutable state) ─────────────────────────────────────────

class _OrganizeWorker:

    def __init__(
        self,
        source: Path,
        destination: Path,
        duplicates: Optional[Path],
        prefer_filename_date: bool,
        update_dates: bool,
        include_hidden: bool,
    ):
        self.source      = source.resolve()
        self.destination = destination.resolve()
        self.duplicates  = duplicates.resolve() if duplicates else None
        self.prefer_filename_date = prefer_filename_date
        self.update_dates  = update_dates
        self.include_hidden = include_hidden

        # hash → path of first successfully moved file
        # Written ONLY after a confirmed move — never a placeholder
        self._seen: Dict[str, Path] = {}

        # Hashes currently mid-move in another thread
        # Prevents two threads from both treating the same content as "new"
        self._in_flight: Set[str] = set()
        self._in_flight_cond = threading.Condition()

        # Protects _seen and counters
        self._lock = threading.Lock()

        self.moved   = 0
        self.dupes   = 0
        self.skipped = 0
        self.errors  = 0

    # ── Collection ────────────────────────────────────────────────────────────

    def _collect(self) -> List[Path]:
        all_files: List[Path] = []
        hidden_count = 0

        for p in self.source.rglob("*"):
            if not p.is_file() or p.is_symlink():
                continue

            # Check the path relative to source so we only inspect the
            # parts that are under the source root, not the root itself
            relative = p.relative_to(self.source)
            if not self.include_hidden and _is_hidden(relative):
                log.debug("SKIP hidden | file=%s", p)
                hidden_count += 1
                continue

            all_files.append(p)

        if hidden_count:
            log.info("Skipped %d hidden file(s) (pass --include-hidden to process them)",
                     hidden_count)
        log.info("Found %d file(s) to process under %s", len(all_files), self.source)
        return all_files

    # ── Per-file processing ───────────────────────────────────────────────────

    def _process(self, path: Path) -> None:
        # Phase 1 — read only, file never mutated
        digest = file_hash(path)
        if digest is None:
            with self._lock:
                self.errors += 1
            return

        date = resolve_date(path, self.prefer_filename_date)
        if date is None:
            with self._lock:
                self.errors += 1
            return

        year  = date.strftime("%Y")
        month = date.strftime("%m")

        # Phase 2 — serialize threads that share the same content hash
        # so duplicate detection is always consistent
        with self._in_flight_cond:
            while digest in self._in_flight:
                self._in_flight_cond.wait()
            self._in_flight.add(digest)

        try:
            with self._lock:
                is_duplicate  = digest in self._seen
                first_seen_at = self._seen.get(digest)

            if is_duplicate:
                self._move_duplicate(path, date, year, month, first_seen_at)
            else:
                self._move_new(path, date, year, month, digest)
        finally:
            with self._in_flight_cond:
                self._in_flight.discard(digest)
                self._in_flight_cond.notify_all()

    def _move_new(
        self, path: Path, date: datetime, year: str, month: str, digest: str
    ) -> None:
        dest_dir = self.destination / year / month
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            log.error("SKIP | cannot create dir | dir=%s | reason=%s", dest_dir, exc)
            with self._lock:
                self.errors += 1
            return

        dest = safe_dest_path(dest_dir, path.name)

        if not move_file(path, dest):
            with self._lock:
                self.errors += 1
            return  # hash NOT registered — next run will retry correctly

        if self.update_dates:
            set_file_dates(dest, date)

        with self._lock:
            self._seen[digest] = dest
            self.moved += 1
        log.info("MOVED | file=%s | dest=%s", path.name, dest)

    def _move_duplicate(
        self,
        path: Path,
        date: datetime,
        year: str,
        month: str,
        first_seen_at: Optional[Path],
    ) -> None:
        if self.duplicates is None:
            log.warning("DUPLICATE skipped (no --duplicates dir) | file=%s | original=%s",
                        path, first_seen_at)
            return

        dest_dir = self.duplicates / year / month
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            log.error("SKIP | cannot create duplicates dir | dir=%s | reason=%s", dest_dir, exc)
            with self._lock:
                self.errors += 1
            return

        dest = safe_dest_path(dest_dir, path.name)

        if not move_file(path, dest):
            with self._lock:
                self.errors += 1
            return  # file left untouched

        if self.update_dates:
            set_file_dates(dest, date)

        with self._lock:
            self.dupes += 1
        log.info("DUPLICATE | file=%s | original=%s | moved_to=%s",
                 path.name, first_seen_at, dest)

    # ── Runner ────────────────────────────────────────────────────────────────

    def run(self, threads: int = 10) -> None:
        files = self._collect()
        if not files:
            log.warning("No files found. Nothing to do.")
            return

        log.info("Starting with %d thread(s)…", threads)
        with ThreadPoolExecutor(max_workers=threads) as pool:
            futures = {pool.submit(self._process, f): f for f in files}
            for future in as_completed(futures):
                future.result()

        log.info("Done.  Moved: %d  |  Duplicates: %d  |  Errors: %d",
                 self.moved, self.dupes, self.errors)
