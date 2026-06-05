#!/usr/bin/env python3
"""
File Organizer Toolkit — entry point
Dispatches to the appropriate command based on the first CLI argument.
"""

import sys
import logging
import argparse

from commands.organize import OrganizeCommand
from commands.clean import CleanCommand
from commands.delete_prefixed import DeletePrefixedCommand

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


COMMANDS = {
    "organize": OrganizeCommand,
    "clean":    CleanCommand,
    "delete":   DeletePrefixedCommand,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="organizer",
        description="File Organizer Toolkit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join([
            "commands:",
            "  organize   Move files into year/month folders by date",
            "  clean      Delete empty directories (including empty subtrees)",
            "  delete     Delete files whose names start with a given prefix",
            "",
            "Run 'organizer <command> --help' for per-command options.",
        ]),
    )
    parser.add_argument("command", choices=COMMANDS.keys(), help="Command to run")
    return parser


def main() -> None:
    # Need at least one argument
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        build_parser().print_help()
        sys.exit(0)

    command_name = sys.argv[1]
    if command_name not in COMMANDS:
        print(f"ERROR: unknown command '{command_name}'. "
              f"Choose from: {', '.join(COMMANDS)}", file=sys.stderr)
        sys.exit(1)

    command_cls = COMMANDS[command_name]
    command = command_cls()
    command.run(sys.argv[2:])  # pass remaining args to the command


if __name__ == "__main__":
    main()
