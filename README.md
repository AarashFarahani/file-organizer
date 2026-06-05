# File Organizer Toolkit

A multithreaded command-line toolkit that organizes, cleans, and sanitizes file collections.
Files are organized by date into a `YYYY/MM/` folder structure, duplicates are detected by
content hash, and junk files (hidden, prefixed) can be removed separately.

## Requirements

- Python 3.9 or newer (standard library only — no `pip install` needed)
- macOS: `osascript` for setting file creation dates (built-in, no install needed)

## Setup

```bash
chmod +x run.sh
```

## Commands

| Command    | Description |
|------------|-------------|
| `organize` | Move files into `YYYY/MM/` folders by date |
| `clean`    | Delete empty directories (including dirs with only empty subdirs) |
| `delete`   | Delete files whose names start with a given prefix |

```bash
./run.sh --help
./run.sh <command> --help
```

---

## `organize`

Recursively scans a source directory and moves every file into a date-based folder tree.

**Date resolution (default behaviour)**

1. Parse date from the filename — supports common camera and app naming conventions
2. Fall back to filesystem creation date (`st_birthtime` on macOS, `mtime` on Linux)

This is the right approach for files uploaded via apps like Documents by Readdle over
SMB/Samba, where the filesystem resets the creation date on arrival. The filename
date is always more reliable in that case.

**Supported filename date formats**

| Example | Source |
|---------|--------|
| `2025-07-26 17.58.48.mov` | Documents by Readdle, iOS screenshots |
| `2025-07-26 17:58:48.mp4` | Colon variant |
| `2025-07-26_17-58-48.jpg` | Underscore/dash variant |
| `20250726_175848.jpg` | WhatsApp, Samsung, Android cameras |
| `20250726175848.jpg` | Compact no-separator |
| `2025-07-26.pdf` | Date only |
| `20250726.pdf` | Date only compact |

**Duplicate detection**

Files are compared by MD5 content hash — not by filename. Identical files are moved to
the `--duplicates` directory. If a filename already exists at the destination, underscores
are appended until the name is free: `photo_.jpg`, `photo__.jpg`, and so on.

**Hidden files**

By default, hidden files (names starting with `.`) and files inside hidden directories
are skipped. Pass `--include-hidden` to process them.

**After a successful move**, both the modified date and creation date are updated to match
the resolved date. On macOS, creation date is set via `osascript`. On Linux, only the
modified date is updated.

If a file cannot be read, moved, or processed for any reason it is left untouched and
the error is logged. Files are never deleted on failure.

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `-s, --source` | *(required)* | Directory to scan recursively |
| `-d, --destination` | *(required)* | Root output directory |
| `--duplicates` | *(none)* | Directory for duplicate files; duplicates are skipped if omitted |
| `-t, --threads` | `10` | Thread-pool size |
| `--use-filesystem-date` | off | Always use filesystem date; skip filename parsing |
| `--no-update-dates` | off | Skip updating creation/modified dates after move |
| `--include-hidden` | off | Include hidden files and files inside hidden directories |
| `-v, --verbose` | off | Enable DEBUG logging |

### Examples

```bash
# Basic
./run.sh organize -s ~/Downloads -d ~/Organized

# With duplicates folder and 20 threads
./run.sh organize -s ~/Downloads -d ~/Organized --duplicates ~/Dupes -t 20

# Skip filename date parsing, use filesystem date only
./run.sh organize -s ~/Downloads -d ~/Organized --use-filesystem-date

# Include hidden files
./run.sh organize -s ~/Downloads -d ~/Organized --include-hidden

# Full example
./run.sh organize -s ~/Downloads -d ~/Organized --duplicates ~/Dupes -t 20 --include-hidden -v
```

### Output structure

```
<destination>/
  2024/
    06/
      IMG_001.jpg
      document.pdf
  2023/
    12/
      family_photo.jpg

<duplicates>/
  2024/
    06/
      IMG_001_.jpg       ← underscore appended to avoid clash
      IMG_001__.jpg      ← second duplicate
```

---

## `clean`

Deletes empty directories recursively. A directory is considered empty if it contains
no files anywhere in its subtree — nested empty subdirectories don't count.
Processes deepest directories first so parents are cleaned up automatically.

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `target` | *(required)* | Root directory to clean |
| `--dry-run` | off | Preview deletions without removing anything |
| `-v, --verbose` | off | Also log directories that are kept |

### Examples

```bash
# Preview first
./run.sh clean --dry-run ~/Organized

# Delete
./run.sh clean ~/Organized

# Combine with organize — clean up leftover empty dirs after moving files
./run.sh organize -s ~/Downloads -d ~/Organized && ./run.sh clean ~/Downloads
```

---

## `delete`

Deletes all files whose names start with a given prefix, recursively. Runs multithreaded.
Default prefix is `._` — the macOS resource fork / metadata files that appear when
copying to non-HFS+ volumes (Samba shares, FAT drives, etc).

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `target` | *(required)* | Directory to scan recursively |
| `--prefix` | `._` | Delete files whose names start with this string |
| `--dry-run` | off | Preview deletions without removing anything |
| `-t, --threads` | `10` | Thread-pool size |
| `-v, --verbose` | off | Enable DEBUG logging |

### Examples

```bash
# Preview with default prefix ._
./run.sh delete --dry-run ~/Organized

# Delete ._  files
./run.sh delete ~/Organized

# Custom prefix
./run.sh delete ~/Organized --prefix ".DS_Store"
./run.sh delete ~/Downloads --prefix "Thumbs" -t 20
```

---

## Project structure

```
file-organizer/
  main.py                  ← entry point / command dispatcher
  run.sh                   ← shell wrapper
  commands/
    base.py                ← BaseCommand ABC (build_parser + execute + run)
    utils.py               ← shared utilities (hashing, date parsing, move, stamping)
    organize.py            ← OrganizeCommand
    clean.py               ← CleanCommand
    delete_prefixed.py     ← DeletePrefixedCommand
```

## Running with Python directly

```bash
python3 main.py organize -s /path/to/source -d /path/to/destination
python3 main.py clean /path/to/directory
python3 main.py delete /path/to/directory --prefix "._"
```

## Background execution

```bash
# Run in background, log to file
nohup ./run.sh organize -s ~/Downloads -d ~/Organized > organizer.log 2>&1 &
echo $!   # print PID to track progress

# Check if still running
ps -p <PID>

# Follow logs live
tail -f organizer.log
```
