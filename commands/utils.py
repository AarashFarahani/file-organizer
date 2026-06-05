"""
Shared utility functions used across commands.
"""

import os
import re
import hashlib
import logging
import platform
import subprocess
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)

IS_MACOS = platform.system() == "Darwin"

# ── Filename date patterns (in priority order) ────────────────────────────────

FILENAME_DATE_PATTERNS: List[Tuple[re.Pattern, str, str]] = [
    # 2025-07-26 17.58.48  (Documents by Readdle, Screenshot style)
    (re.compile(r"(?P<dt>\d{4}-\d{2}-\d{2} \d{2}\.\d{2}\.\d{2})"), "%Y-%m-%d %H.%M.%S", "YYYY-MM-DD HH.MM.SS"),
    # 2025-07-26 17:58:48
    (re.compile(r"(?P<dt>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"),   "%Y-%m-%d %H:%M:%S", "YYYY-MM-DD HH:MM:SS"),
    # 2025-07-26_17-58-48
    (re.compile(r"(?P<dt>\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})"),   "%Y-%m-%d_%H-%M-%S", "YYYY-MM-DD_HH-MM-SS"),
    # 20250726_175848  (WhatsApp, Samsung, Android cameras)
    (re.compile(r"(?P<dt>\d{8}_\d{6})"),                             "%Y%m%d_%H%M%S",     "YYYYMMDD_HHMMSS"),
    # 20250726175848
    (re.compile(r"(?P<dt>\d{14})"),                                  "%Y%m%d%H%M%S",      "YYYYMMDDHHMMSS"),
    # 2025-07-26
    (re.compile(r"(?P<dt>\d{4}-\d{2}-\d{2})"),                      "%Y-%m-%d",          "YYYY-MM-DD"),
    # 20250726
    (re.compile(r"(?P<dt>\d{8})"),                                   "%Y%m%d",            "YYYYMMDD"),
]


# ── Date resolution ───────────────────────────────────────────────────────────

def date_from_filename(path: Path) -> Optional[datetime]:
    """Try each pattern against the filename stem. Return first valid parse."""
    name = path.stem
    for pattern, fmt, description in FILENAME_DATE_PATTERNS:
        m = pattern.search(name)
        if m:
            try:
                dt = datetime.strptime(m.group("dt"), fmt)
                log.debug("DATE from filename | file=%s | pattern=%s | parsed=%s",
                          path.name, description, dt)
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
    """Return the date to use for organising. Filename-first unless overridden."""
    if prefer_filename:
        dt = date_from_filename(path)
        if dt:
            return dt
        log.debug("No date in filename, falling back to filesystem | file=%s", path.name)
    return date_from_filesystem(path)


# ── File stamping ─────────────────────────────────────────────────────────────

def set_file_dates(path: Path, dt: datetime) -> None:
    """
    Set modified date (all platforms) and creation date (macOS via osascript).
    Failures are warnings only — never abort the caller.
    """
    ts = dt.timestamp()

    # Modified date
    try:
        os.utime(path, (ts, ts))
        log.debug("DATE SET modified | file=%s | date=%s", path.name, dt)
    except Exception as exc:
        log.warning("Could not set modified date | file=%s | reason=%s", path, exc)

    # Creation date — macOS only
    if not IS_MACOS:
        return

    mac_date = dt.strftime("%m/%d/%Y %H:%M:%S")
    script = (
        f'tell application "Finder" to '
        f'set creation date of (POSIX file "{path}") to date "{mac_date}"'
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            log.warning("Could not set creation date | file=%s | osascript=%s",
                        path, result.stderr.strip())
        else:
            log.debug("DATE SET creation | file=%s | date=%s", path.name, dt)
    except subprocess.TimeoutExpired:
        log.warning("Could not set creation date | file=%s | reason=osascript timeout", path)
    except Exception as exc:
        log.warning("Could not set creation date | file=%s | reason=%s", path, exc)


# ── File I/O helpers ──────────────────────────────────────────────────────────

def file_hash(path: Path, chunk: int = 65_536) -> Optional[str]:
    """MD5 digest of file contents. None on any read failure."""
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
    """
    Move src → dest. Returns True on success.
    On failure: logs reason, leaves src untouched, returns False.
    """
    try:
        import shutil
        shutil.move(str(src), dest)
        return True
    except Exception as exc:
        log.error("SKIP | cannot move file | file=%s | target=%s | reason=%s",
                  src, dest, exc)
        return False
