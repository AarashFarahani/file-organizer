#!/usr/bin/env python3
"""
File Organizer
Moves files from source to destination, organized by date (year/month).
Date is extracted from filename first, falls back to file creation date.
After a successful move, sets both creation date and modified date on macOS.
Duplicate files are moved to a separate duplicates directory.
"""

import os
import re
import sys
import shutil
import hashlib
import logging
import argparse
import platform
import subprocess
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Date patterns to try against filenames (in priority order) ───────────────

FILENAME_DATE_PATTERNS: List[Tuple[re.Pattern, str, str]] = [
    # 2025-07-26 17.58.48  (Documents by Readdle, Screenshot style)
    (
        re.compile(r"(?P<dt>\d{4}-\d{2}-\d{2} \d{2}\.\d{2}\.\d{2})"),
        "%Y-%m-%d %H.%M.%S",
        "YYYY-MM-DD HH.MM.SS",
    ),
    # 2025-07-26 17:58:48
    (
        re.compile(r"(?P<dt>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"),
        "%Y-%m-%d %H:%M:%S",
        "YYYY-MM-DD HH:MM:SS",
    ),
    # 2025-07-26_17-58-48
    (
        re.compile(r"(?P<dt>\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})"),
        "%Y-%m-%d_%H-%M-%S",
        "YYYY-MM-DD_HH-MM-SS",
    ),
    # 20250726_175848  (WhatsApp, Samsung, many Android cameras)
    (
        re.compile(r"(?P<dt>\d{8}_\d{6})"),
        "%Y%m%d_%H%M%S",
        "YYYYMMDD_HHMMSS",
    ),
    # 20250726175848
    (
        re.compile(r"(?P<dt>\d{14})"),
        "%Y%m%d%H%M%S",
        "YYYYMMDDHHMMSS",
    ),
    # 2025-07-26  (date only)
    (
        re.compile(r"(?P<dt>\d{4}-\d{2}-\d{2})"),
        "%Y-%m-%d",
        "YYYY-MM-DD",
    ),
    # 20250726  (date only, compact)
    (
        re.compile(r"(?P<dt>\d{8})"),
        "%Y%m%d",
        "YYYYMMDD",
    ),
]


# ── Date helpers ──────────────────────────────────────────────────────────────

def date_from_filename(path: Path) -> Optional[datetime]:
    """Try to extract a date from the filename. Returns None if no pattern matched."""
    name = path.stem
    for pattern, fmt, description in FILENAME_DATE_PATTERNS:
        m = pattern.search(name)
        if m:
            raw = m.group("dt")
            try:
                dt = datetime.strptime(raw, fmt)
                log.debug(
                    "DATE from filename | file=%s | pattern=%s | parsed=%s",
                    path.name, description, dt,
                )
                return dt
            except ValueError:
                continue
    return None


def date_from_filesystem(path: Path) -> Optional[datetime]:
    """Return st_birthtime (macOS) or st_mtime fallback. None on failure."""
    try:
        stat = path.stat()
        birth = getattr(stat, "st_birthtime", None)
        ts = birth if birth else stat.st_mtime
        return datetime.fromtimestamp(ts)
    except Exception as exc:
        log.error("SKIP | cannot read filesystem date | file=%s | reason=%s", path, exc)
        return None


def resolve_date(path: Path, prefer_filename: bool) -> Optional[datetime]:
    """Return the date to use for organising this file."""
    if prefer_filename:
        dt = date_from_filename(path)
        if dt:
            return dt
        log.debug("No date in filename, falling back to filesystem | file=%s", path.name)
    return date_from_filesystem(path)


# ── Date stamping ─────────────────────────────────────────────────────────────

IS_MACOS = platform.system() == "Darwin"


def set_file_dates(path: Path, dt: datetime) -> None:
    """
    Set both the modification date and the creation (birth) date of a file.

    Modified date : set via os.utime() — works on all platforms.
    Creation date : set via osascript — macOS only.

    Failures are logged as warnings; they never abort the organizer.
    """
    ts = dt.timestamp()

    # ── Modified date (cross-platform) ───────────────────────────────────────
    try:
        os.utime(path, (ts, ts))
        log.debug("DATE SET modified | file=%s | date=%s", path.name, dt)
    except Exception as exc:
        log.warning(
            "Could not set modified date | file=%s | reason=%s", path, exc
        )

    # ── Creation date (macOS only via osascript) ──────────────────────────────
    if not IS_MACOS:
        return

    # osascript expects: "MM/DD/YYYY HH:MM:SS"
    mac_date = dt.strftime("%m/%d/%Y %H:%M:%S")
    script = (
        f'tell application "Finder" to '
        f'set creation date of (POSIX file "{path}") to date "{mac_date}"'
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            log.warning(
                "Could not set creation date | file=%s | osascript error=%s",
                path, result.stderr.strip(),
            )
        else:
            log.debug("DATE SET creation | file=%s | date=%s", path.name, dt)
    except subprocess.TimeoutExpired:
        log.warning("Could not set creation date | file=%s | reason=osascript timeout", path)
    except Exception as exc:
        log.warning("Could not set creation date | file=%s | reason=%s", path, exc)


# ── File helpers ──────────────────────────────────────────────────────────────

def file_hash(path: Path, chunk: int = 65_536) -> Optional[str]:
    """Return MD5 hex-digest. Returns None and logs on read failure."""
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


def safe_dest_path(dest_dir: Path, filename: str) -> Path:
    """
    Return a free path inside dest_dir.
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
    """Move src to dest. Returns True on success; logs and returns False on any failure."""
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
        prefer_filename_date: bool = True,
        update_dates: bool = True,
    ):
        self.source = source.resolve()
        self.destination = destination.resolve()
        self.duplicates = duplicates.resolve() if duplicates else None
        self.prefer_filename_date = prefer_filename_date
        self.update_dates = update_dates

        self._seen: Dict[str, Path] = {}
        self._in_flight: Set[str] = set()
        self._in_flight_cond = threading.Condition()
        self._lock = threading.Lock()

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
        # ── Phase 1: read — file never mutated ───────────────────────────────
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

        # ── Phase 2: serialize threads with the same hash ────────────────────
        with self._in_flight_cond:
            while digest in self._in_flight:
                self._in_flight_cond.wait()
            self._in_flight.add(digest)

        try:
            with self._lock:
                is_duplicate = digest in self._seen
                first_seen_at = self._seen.get(digest)

            if is_duplicate:
                self._handle_duplicate(path, date, year, month, first_seen_at)
            else:
                self._handle_new(path, date, year, month, digest)
        finally:
            with self._in_flight_cond:
                self._in_flight.discard(digest)
                self._in_flight_cond.notify_all()

    def _handle_new(
        self, path: Path, date: datetime, year: str, month: str, digest: str
    ) -> None:
        dest_dir = self.destination / year / month
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            log.error(
                "SKIP | cannot create destination dir | dir=%s | reason=%s", dest_dir, exc
            )
            with self._lock:
                self.errors += 1
            return

        dest = safe_dest_path(dest_dir, path.name)
        if not move_file(path, dest):
            with self._lock:
                self.errors += 1
            return

        # Update dates only after confirmed successful move
        if self.update_dates:
            set_file_dates(dest, date)

        with self._lock:
            self._seen[digest] = dest
            self.moved += 1
        log.info("MOVED | file=%s | dest=%s", path.name, dest)

    def _handle_duplicate(
        self,
        path: Path,
        date: datetime,
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
                "SKIP | cannot create duplicates dir | dir=%s | reason=%s", dest_dir, exc
            )
            with self._lock:
                self.errors += 1
            return

        dest = safe_dest_path(dest_dir, path.name)
        if not move_file(path, dest):
            with self._lock:
                self.errors += 1
            return

        # Update dates on duplicates too
        if self.update_dates:
            set_file_dates(dest, date)

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
        description="Organize files by date into year/month folders.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-s", "--source", required=True,
                        help="Source directory to scan recursively.")
    parser.add_argument("-d", "--destination", required=True,
                        help="Destination root directory.")
    parser.add_argument("--duplicates", default=None,
                        help="Directory for duplicate files. Skipped if omitted.")
    parser.add_argument("-t", "--threads", type=int, default=10,
                        help="Thread-pool size.")
    parser.add_argument(
        "--use-filesystem-date",
        action="store_true",
        default=False,
        help="Always use filesystem date. Default: try filename first, fall back to filesystem.",
    )
    parser.add_argument(
        "--no-update-dates",
        action="store_true",
        default=False,
        help="Skip updating creation/modified dates after move. Default: dates are updated.",
    )
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
    prefer_filename_date = not args.use_filesystem_date
    update_dates = not args.no_update_dates

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

    date_mode = "filename → filesystem fallback" if prefer_filename_date else "filesystem only"
    log.info("Date mode: %s", date_mode)
    if update_dates:
        log.info("Date stamping: enabled (creation + modified)%s",
                 " [macOS]" if IS_MACOS else " [modified only — not macOS]")
    else:
        log.info("Date stamping: disabled")

    organizer = Organizer(
        source, destination, duplicates,
        prefer_filename_date=prefer_filename_date,
        update_dates=update_dates,
    )
    organizer.run(threads=args.threads)


if __name__ == "__main__":
    main()
