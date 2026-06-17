"""PyArmor unpacker — DEFERRED TO v2.

This module is preserved as a v2 seed, not exposed in v1. Per
`05_ADVERSARIAL_REVIEW.md` section 4.3, the PyArmor pillar was dropped from v1
because:

  - Lil-House/Pyarmor-Static-Unpack-1shot v0.4.0 supports PyArmor 8.0-9.2.5
    and is being rewritten, with v1.0.0 expected in 2027. When that lands,
    any tool wrapping the existing unpacker is dead code.
  - DMCA Section 1201 trafficking risk is real for the Lil-House binary;
    the safe move is user-supplied `--binary` and an explicit
    pre-PyPI-release lawyer review.

If/when this is revived for v2, the implementation is:
    Detection pass (we run this; static AST/file-pattern analysis)
        |
        v
    Pre-flight gate (we refuse early if version / mode is unsupported)
        |
        v
    Subprocess invocation of Pyarmor-Static-Unpack-1shot (user-supplied binary)
        |
        v
    Re-detection integrity check (sanity-check the output before claiming success)

References (see 03_FEATURE_FEASIBILITY.md -> PyArmor Specialist Deep-Dive):
    https://github.com/Lil-House/Pyarmor-Static-Unpack-1shot
    https://github.com/yoruak1/PyGlimmer (vendored Pyarmor-Static-Unpack-1shot fork)
    https://pyarmor.readthedocs.io/en/latest/
"""

from __future__ import annotations

__all__: list[str] = []  # Nothing exported in v1.

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from pydantic import BaseModel, Field
from rich.console import Console
from rich.table import Table

# Local imports
from pyglimmer_toolkit.utils.hashing import sha256_of_file

console = Console(stderr=True)

ProgressCallback = Callable[[float, str], None]


class PyArmorVersion(str, Enum):
    """Detected PyArmor versions we know how to handle."""

    V6 = "6.x"
    V7 = "7.x"
    V8 = "8.x"
    V9_0 = "9.0"
    V9_1 = "9.1"
    V9_2 = "9.2.x"
    V9_3_PLUS = "9.3+"  # Unsupported — flagged, refused
    UNKNOWN = "unknown"


class PyArmorMode(str, Enum):
    """Detected protection modes."""

    PLAIN = "plain"
    RFT = "rft"  # Rename Functions and Transform
    BCC = "bcc"  # Mixed Python + C — UNSUPPORTED in v1
    RESTRICT = "restrict"  # Anti-debug — UNSUPPORTED in v1
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PyArmorConfig:
    """Inputs to a PyArmor unpack job."""

    target: Path
    out_dir: Path
    # Future: timeout_seconds, llm_assist, dry_run, ...


class DetectionReport(BaseModel):
    """Result of running PyArmor detection on a target."""

    is_pyarmor: bool
    version: PyArmorVersion = PyArmorVersion.UNKNOWN
    mode: PyArmorMode = PyArmorMode.UNKNOWN
    target_sha256: str
    target_size_bytes: int
    detection_notes: list[str] = Field(default_factory=list)

    @property
    def is_unsupported_version(self) -> bool:
        """True if the detected version is one we explicitly do not support."""
        return self.version in {PyArmorVersion.V6, PyArmorVersion.V7, PyArmorVersion.V9_3_PLUS}

    @property
    def is_unsupported_mode(self) -> bool:
        """True if the detected mode (BCC, restrict) is one we do not support."""
        return self.mode in {PyArmorMode.BCC, PyArmorMode.RESTRICT}

    def summary_table(self) -> Table:
        """Render the detection report as a Rich table for CLI output."""
        table = Table(title="PyArmor Detection", show_header=True, header_style="bold cyan")
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        table.add_row("is_pyarmor", str(self.is_pyarmor))
        table.add_row("version", self.version.value)
        table.add_row("mode", self.mode.value)
        table.add_row("target_sha256", self.target_sha256)
        table.add_row("target_size_bytes", str(self.target_size_bytes))
        if self.detection_notes:
            table.add_row("notes", "\n".join(self.detection_notes))
        return table


class UnpackResult(BaseModel):
    """Result of an unpack attempt."""

    success: bool
    exit_code: int = 0  # 0 ok, 2 unpacker-error, 3 unsupported-version, 4 integrity-failed
    target_sha256: str
    out_dir: Path
    unpacked_files: list[Path] = Field(default_factory=list)
    error_message: Optional[str] = None
    duration_seconds: float = 0.0

    def summary_panel(self):
        """Render a Rich panel summarizing the unpack outcome."""
        from rich.panel import Panel

        if self.success:
            body = (
                f"[green]Unpacked {len(self.unpacked_files)} file(s)[/green]\n"
                f"Output: {self.out_dir}\n"
                f"Duration: {self.duration_seconds:.2f}s"
            )
        else:
            body = (
                f"[red]Unpack failed (exit {self.exit_code})[/red]\n"
                f"Reason: {self.error_message or 'unknown'}"
            )
        return Panel(body, title="PyArmor Unpack", border_style="green" if self.success else "red")


class PyArmorUnpacker:
    """Orchestrates detection + unpack of a PyArmor-protected script.

    Implementation status: STUB. The detection method here does the actual work
    (it's cheap and runs in-process). The unpack method must be implemented by
    wrapping Lil-House/Pyarmor-Static-Unpack-1shot.
    """

    def __init__(self, config: PyArmorConfig) -> None:
        self._config = config

    def detect(self) -> DetectionReport:
        """Run the static detection pass.

        Detects (best-effort, by file content patterns):
            - `pyarmor_runtime` / `__pyarmor__` / `pytransform` imports
            - The version-marker strings embedded in PyArmor's native shim
            - The mode markers (RFT, BCC, restrict) where present

        Implementation status: STUB. Returns a placeholder that says "not detected"
        until the heuristics are wired up.
        """
        target = self._config.target
        if not target.exists():
            raise FileNotFoundError(f"Target does not exist: {target}")

        # NOTE: a real implementation would read the first 4KB and grep for the
        # PyArmor shim import patterns. For the skeleton we just compute the hash.
        target_hash = sha256_of_file(target)
        size = target.stat().st_size

        return DetectionReport(
            is_pyarmor=False,  # STUB
            version=PyArmorVersion.UNKNOWN,
            mode=PyArmorMode.UNKNOWN,
            target_sha256=target_hash,
            target_size_bytes=size,
            detection_notes=[
                "STUB: detection heuristics not yet implemented. "
                "See 03_FEATURE_FEASIBILITY.md -> PyArmor Specialist Deep-Dive."
            ],
        )

    def unpack(self, on_progress: ProgressCallback) -> UnpackResult:
        """Unpack the target.

        Implementation status: STUB.

        The real implementation will:
            1. Run detection first.
            2. If unsupported -> return early with exit_code=3.
            3. Create out_dir, write a `.pyglimmer_cache/` directory.
            4. Locate the vendored pyarmor-static-unpack-1shot binary
               (downloaded at install time, pinned to v0.4.0).
            5. Subprocess it with timeout, parse stdout for progress lines.
            6. Verify the output is real Python (re-run detection on it).
            7. Return UnpackResult with the list of unpacked files.
        """
        on_progress(0.0, "STUB: unpack not implemented")
        raise NotImplementedError(
            "PyArmorUnpacker.unpack is a stub. "
            "Implement by wrapping Lil-House/Pyarmor-Static-Unpack-1shot. "
            "See 03_FEATURE_FEASIBILITY.md -> PyArmor Specialist Deep-Dive."
        )
