"""Subprocess management with cancellation support.

The stripper pipeline shells out to:
    - pyinstxtractor (PyInstaller bundles)
    - pycdc (Python bytecode decompiler)
    - pylingual (Python 3.11+ decompiler)
    - The .NET sidecar (C# deobfuscator)
    - Ollama / anthropic / openai CLIs (LLM cleanup, when not using Python libs)

All subprocess invocations go through `run_with_cancel` so the GUI's Cancel button
can interrupt them cleanly.
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Optional


class SubprocessCancelled(Exception):
    """Raised when a subprocess is cancelled via the cancel event."""


def run_with_cancel(
    args: list[str],
    *,
    cwd: Optional[Path] = None,
    timeout_seconds: Optional[int] = None,
    cancel_event: Optional[threading.Event] = None,
    env: Optional[dict[str, str]] = None,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess, supporting cooperative cancellation.

    Args:
        args: Command and arguments.
        cwd: Working directory for the subprocess.
        timeout_seconds: Hard timeout. None = wait forever.
        cancel_event: If provided and set, the subprocess is terminated and a
            SubprocessCancelled is raised.
        env: Environment variables. None = inherit parent.

    Returns:
        subprocess.CompletedProcess with captured stdout/stderr.

    Raises:
        SubprocessCancelled: If cancel_event was set before/during the run.
        subprocess.TimeoutExpired: If timeout_seconds elapsed.
        FileNotFoundError: If `args[0]` is not executable.
    """
    # Implementation note: a real implementation should poll cancel_event on a
    # background thread and call .terminate() / .kill() on the subprocess.
    # This stub just runs the subprocess straight through.
    del cancel_event  # unused in stub

    return subprocess.run(
        args,
        cwd=cwd,
        timeout=timeout_seconds,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def is_windows() -> bool:
    """True if running on Windows."""
    import sys

    return sys.platform.startswith("win")
