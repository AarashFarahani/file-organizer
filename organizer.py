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
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────

def file_hash(path: Path, chunk: int = 65_536) -> str:
    """Return MD5 hex-digest of a file (fast duplicate detection)."""
    h = hashlib.md5()
    with open(path, "rb") as fh:
        while True:
            data = fh.read(chunk)
            if not data:
                break
            h.update(data)
    return h.hexdigest()


def creation_date(path: Path) -> datetime:
    """
    Return the best available creation/birth date for a file.
    Falls back to mtime on Linux where birthtime is unavailable.
    """
    stat = path.stat()
    birth = getattr(stat, "st_birthtime", None)
    ts = birth if birth else stat.st_mtime
    return datetime.fromtimestamp(ts)


def safe_dest_path(dest_dir: Path, filename: str) -> Path:
    """
    Return a path inside dest_dir that does not already exist.
    If <filename> is taken, append underscores: file_.jpg, file__.jpg …
    """
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    candidate = dest_dir / filename
    while candidate.exists():
        stem += "_"
        candidate = dest_dir / f"{stem}{suffix}"
    return candidate


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

        # hash → destination path (tracks files already moved)
        self._seen: Dict[str, Path] = {}
        self._lock = threading.Lock()

        # counters (protected by _lock)
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
        try:
            # ── Heavy I/O done OUTSIDE the lock ──────────────────────────────
            digest = file_hash(path)        # read entire file — no lock needed
            date = creation_date(path)

            year  = date.strftime("%Y")
            month = date.strftime("%m")

            # ── Lock only to check/update the seen-hash registry ─────────────
            with self._lock:
                is_duplicate = digest in self._seen
                if not is_duplicate:
                    # Reserve this hash so other threads don't race on it
                    self._seen[digest] = None  # placeholder until move is done

            # ── File move done OUTSIDE the lock ──────────────────────────────
            if is_duplicate:
                if self.duplicates is None:
                    log.warning("DUPLICATE skipped (no duplicates dir): %s", path)
                    return

                dest_dir = self.duplicates / year / month
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = safe_dest_path(dest_dir, path.name)
                shutil.move(str(path), dest)

                with self._lock:
                    self.dupes += 1
                log.info("DUPLICATE  %s  →  %s", path.name, dest)

            else:
                dest_dir = self.destination / year / month
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = safe_dest_path(dest_dir, path.name)
                shutil.move(str(path), dest)

                with self._lock:
                    self._seen[digest] = dest   # update placeholder with real path
                    self.moved += 1
                log.info("MOVED      %s  →  %s", path.name, dest)

        except Exception as exc:
            with self._lock:
                self.errors += 1
            log.error("ERROR processing %s: %s", path, exc)

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
