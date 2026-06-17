"""Module entry point: `python -m pyglimmer_toolkit`.

This is the canonical invocation. It exists as a separate file from `cli.py` so
that `python -m pyglimmer_toolkit` resolves cleanly without depending on the
[project.scripts] entry point being installed.
"""

from __future__ import annotations

import sys

from pyglimmer_toolkit.cli import app


def main() -> int:
    """Run the Typer CLI and return its exit code.

    Returns:
        Process exit code (0 = success, non-zero = error).
    """
    # Typer's app.__call__ raises SystemExit on --help / errors, which is the
    # correct behavior for a CLI entry point.
    app()
    return 0


if __name__ == "__main__":
    sys.exit(main())
