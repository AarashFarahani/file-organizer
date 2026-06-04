#!/usr/bin/env python3
"""
File Organizer
Moves files from source to destination, organized by date (year/month).
Duplicate files are moved to a separate duplicates directory.
"""

import sys
import shutil
import hashlib
import logging
import argparse
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Set
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────

def file_hash(path: Path, chunk: int = 65_536) -> Optional[str]:
    """
    Return MD5 hex-digest of a file.
    Returns None and logs if the file cannot be read.
    """
    try:
        h = hashlib.md5()
        with open(path, "rb") as fh:
            while True:
                data = fh.read(chunk)
                if not data:
                    break
                h.update(data)
        return h.hexdigest()
    except Exception as exc:
        log.error("SKIP | cannot read file | file=%s | reason=%s", path, exc)
        return None


def creation_date(path: Path) -> Optional[datetime]:
    """
    Return the best available creation/birth date for a file.
    Falls back to mtime on Linux where birthtime is unavailable.
    Returns None and logs if stat fails.
    """
    try:
        stat = path.stat()
        birth = getattr(stat, "st_birthtime", None)
        ts = birth if birth else stat.st_mtime
        return datetime.fromtimestamp(ts)
    except Exception as exc:
        log.error("SKIP | cannot read date | file=%s | reason=%s", path, exc)
        return None


def safe_dest_path(dest_dir: Path, filename: str) -> Path:
    """
    Return a path inside dest_dir that does not already exist.
    Appends underscores to the stem until the name is free:
      photo.jpg → photo_.jpg → photo__.jpg → …
    """
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    candidate = dest_dir / filename
    while candidate.exists():
        stem += "_"
        candidate = dest_dir / f"{stem}{suffix}"
    return candidate


def move_file(src: Path, dest: Path) -> bool:
    """
    Move src to dest. Returns True on success, False on any failure.
    The source file is NEVER deleted if the move fails.
    """
    try:
        shutil.move(str(src), dest)
        return True
    except Exception as exc:
        log.error(
            "SKIP | cannot move file | file=%s | target=%s | reason=%s",
            src, dest, exc,
        )
        return False


# ── Core worker ───────────────────────────────────────────────────────────────

class Organizer:
    def __init__(
        self,
        source: Path,
        destination: Path,
        duplicates: Optional[Path],
    ):
        self.source = source.resolve()
        self.destination = destination.resolve()
        self.duplicates = duplicates.resolve() if duplicates else None

        # hash → destination path of the FIRST successfully moved file
        # Never written until a move is confirmed successful
        self._seen: Dict[str, Path] = {}

        # Tracks hashes currently being processed by another thread,
        # so a racing thread waits rather than double-moving
        self._in_flight: Set[str] = set()
        self._in_flight_cond = threading.Condition()

        self._lock = threading.Lock()

        # counters
        self.moved = 0
        self.dupes = 0
        self.errors = 0

    def collect_files(self) -> List[Path]:
        files = [
            p for p in self.source.rglob("*")
            if p.is_file() and not p.is_symlink()
        ]
        log.info("Found %d file(s) under %s", len(files), self.source)
        return files

    def process(self, path: Path) -> None:
        # ── Phase 1: read — no lock, file never mutated here ─────────────────
        digest = file_hash(path)
        if digest is None:
            with self._lock:
                self.errors += 1
            return  # already logged inside file_hash

        date = creation_date(path)
        if date is None:
            with self._lock:
                self.errors += 1
            return  # already logged inside creation_date

        year  = date.strftime("%Y")
        month = date.strftime("%m")

        # ── Phase 2: wait if another thread is mid-move for the same hash ────
        # This prevents a race where two identical files both look "new"
        # because neither has finished moving yet when the other checks _seen.
        with self._in_flight_cond:
            while digest in self._in_flight:
                self._in_flight_cond.wait()
            # Safe to proceed: either already in _seen (duplicate) or truly new
            self._in_flight.add(digest)

        try:
            # ── Phase 3: decide new vs duplicate ─────────────────────────────
            with self._lock:
                is_duplicate = digest in self._seen
                first_seen_at = self._seen.get(digest)

            if is_duplicate:
                self._handle_duplicate(path, year, month, first_seen_at)
            else:
                self._handle_new(path, year, month, digest)

        finally:
            # Always release the in-flight slot so waiting threads unblock
            with self._in_flight_cond:
                self._in_flight.discard(digest)
                self._in_flight_cond.notify_all()

    def _handle_new(self, path: Path, year: str, month: str, digest: str) -> None:
        dest_dir = self.destination / year / month

        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            log.error(
                "SKIP | cannot create destination directory | dir=%s | reason=%s",
                dest_dir, exc,
            )
            with self._lock:
                self.errors += 1
            return  # file untouched

        dest = safe_dest_path(dest_dir, path.name)

        if not move_file(path, dest):
            # move_file already logged the error
            with self._lock:
                self.errors += 1
            return  # do NOT register hash — move never happened

        # Only register hash after confirmed successful move
        with self._lock:
            self._seen[digest] = dest
            self.moved += 1
        log.info("MOVED | file=%s | dest=%s", path.name, dest)

    def _handle_duplicate(
        self,
        path: Path,
        year: str,
        month: str,
        first_seen_at: Optional[Path],
    ) -> None:
        if self.duplicates is None:
            log.warning(
                "DUPLICATE skipped (no --duplicates dir) | file=%s | original=%s",
                path, first_seen_at,
            )
            return

        dest_dir = self.duplicates / year / month

        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            log.error(
                "SKIP | cannot create duplicates directory | dir=%s | reason=%s",
                dest_dir, exc,
            )
            with self._lock:
                self.errors += 1
            return  # file untouched

        dest = safe_dest_path(dest_dir, path.name)

        if not move_file(path, dest):
            # move_file already logged; leave file in place
            with self._lock:
                self.errors += 1
            return

        with self._lock:
            self.dupes += 1
        log.info(
            "DUPLICATE | file=%s | original=%s | moved_to=%s",
            path.name, first_seen_at, dest,
        )

    def run(self, threads: int = 10) -> None:
        files = self.collect_files()
        if not files:
            log.warning("No files found. Nothing to do.")
            return

        log.info("Starting with %d thread(s)…", threads)
        with ThreadPoolExecutor(max_workers=threads) as pool:
            futures = {pool.submit(self.process, f): f for f in files}
            for future in as_completed(futures):
                future.result()

        log.info(
            "Done.  Moved: %d  |  Duplicates: %d  |  Errors: %d",
            self.moved, self.dupes, self.errors,
        )


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Organize files by creation date into year/month folders.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-s", "--source", required=True,
                        help="Source directory to scan recursively.")
    parser.add_argument("-d", "--destination", required=True,
                        help="Destination root directory (year/month structure created here).")
    parser.add_argument("--duplicates", default=None,
                        help="Directory for duplicate files. If omitted, duplicates are skipped.")
    parser.add_argument("-t", "--threads", type=int, default=10,
                        help="Thread-pool size.")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable DEBUG logging.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    source      = Path(args.source)
    destination = Path(args.destination)
    duplicates  = Path(args.duplicates) if args.duplicates else None

    if not source.exists():
        log.error("Source directory does not exist: %s", source)
        sys.exit(1)
    if not source.is_dir():
        log.error("Source is not a directory: %s", source)
        sys.exit(1)

    try:
        source.resolve().relative_to(destination.resolve())
        log.error("Source cannot be inside the destination directory.")
        sys.exit(1)
    except ValueError:
        pass

    destination.mkdir(parents=True, exist_ok=True)
    if duplicates:
        duplicates.mkdir(parents=True, exist_ok=True)

    organizer = Organizer(source, destination, duplicates)
    organizer.run(threads=args.threads)


if __name__ == "__main__":
    main()
