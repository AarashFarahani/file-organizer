# File Organizer

Recursively scans a source directory and moves every file into a date-based folder tree under your destination. Duplicate files (detected by content hash) are kept safely in a separate duplicates directory instead of being overwritten.

## Features

- **Date-based organisation** — `<destination>/YYYY/MM/DD/`
- **Duplicate detection** — content-hash (MD5) comparison, not just filenames
- **Safe naming** — clashing names get underscores appended (`photo_.jpg`, `photo__.jpg` …)
- **Multithreaded** — configurable thread pool (default 10)
- **Non-destructive** — source files are *moved*, not copied; nothing is silently overwritten

## Requirements

- Python 3.9 or newer (standard library only – no `pip install` needed)

## Quick start

```bash
# Make the helper script executable (one-time)
chmod +x run.sh

# Basic usage
./run.sh -s ~/Downloads -d ~/Organized

# With a duplicates folder and 20 threads
./run.sh -s ~/Downloads -d ~/Organized --duplicates ~/Dupes -t 20

# Verbose / debug output
./run.sh -s ~/Downloads -d ~/Organized -v
```

## All options

| Flag | Long form | Default | Description |
|------|-----------|---------|-------------|
| `-s` | `--source` | *(required)* | Directory to scan recursively |
| `-d` | `--destination` | *(required)* | Root output directory |
| | `--duplicates` | *(none)* | Where to put duplicate files; duplicates are skipped if omitted |
| `-t` | `--threads` | `10` | Thread-pool size |
| `-v` | `--verbose` | off | Enable DEBUG-level logging |
| `-h` | `--help` | | Show help |

## Output structure

```
<destination>/
  2024/
    06/
      15/
        IMG_001.jpg
        document.pdf
  2023/
    12/
      25/
        family_photo.jpg

<duplicates>/          ← only when --duplicates is supplied
  2024/
    06/
      15/
        IMG_001_.jpg   ← underscore appended to avoid clash
```

## Running directly with Python

```bash
python3 organizer.py \
  --source      /path/to/source \
  --destination /path/to/destination \
  --duplicates  /path/to/duplicates \
  --threads     20
```
