"""
Base command — all commands inherit from this.
"""

import logging
from abc import ABC, abstractmethod
from typing import List

log = logging.getLogger(__name__)


class BaseCommand(ABC):
    """
    Every command must implement:
      - build_parser() → argparse.ArgumentParser
      - execute(args)  → runs the command given parsed args

    run(argv) handles parsing + verbose flag + calling execute().
    """

    @abstractmethod
    def build_parser(self):
        """Return a configured ArgumentParser for this command."""

    @abstractmethod
    def execute(self, args) -> None:
        """Run the command with already-parsed args."""

    def run(self, argv: List[str]) -> None:
        parser = self.build_parser()
        args = parser.parse_args(argv)

        if hasattr(args, "verbose") and args.verbose:
            logging.getLogger().setLevel(logging.DEBUG)

        self.execute(args)
