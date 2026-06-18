"""Single-pillar pipeline orchestrator (v1 cut-scope).

The v1 pipeline auto-detects the target type and routes to the GenericPythonStripper:

    - PyInstaller bundle (MAGIC + 'MEI\\014\\013\\012\\013\\016') -> extract -> unwrap -> decompile
    - .pyc bytecode (.pyc magic number)                            -> decompile (skip unwrap if no obfuscation detected)
    - .py source                                                    -> run through unwrap only (no decompile needed)

The .NET and PyArmor pillars were dropped from v1 per `05_ADVERSARIAL_REVIEW.md`
and live in v2 backlog.

Implementation status: STUB. The real implementation will:
    1. Read the first 4KB of the target.
    2. Match magic bytes / header patterns against a routing table.
    3. Construct the GenericPythonStripper with the right config.
    4. Run the pipeline; persist state to `.pyglimmer_cache/<sha>/state.json`.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from pydantic import BaseModel, Field
from rich.console import Console
from rich.panel import Panel

from pyglimmer_toolkit.utils.hashing import sha256_of_file

console = Console(stderr=True)

ProgressCallback = Callable[[float, str], None]


class TargetKind(str, Enum):
    """Detected target file kinds."""

    PY_SOURCE = "py_source"  # Plain .py
    PYC_BYTECODE = "pyc_bytecode"  # Compiled .pyc
    PYINSTALLER_BUNDLE = "pyinstaller_bundle"  # Frozen PyInstaller .exe
    UNKNOWN = "unknown"


class PipelineRunResult(BaseModel):
    """Result of a single-pillar pipeline run."""

    success: bool
    target_sha256: str
    target_kind: TargetKind
    stripper_result: Optional["object"] = None  # Forward ref to avoid circular import; populated when wired up
    notes: list[str] = Field(default_factory=list)
    duration_seconds: float = 0.0

    def summary_panel(self):
        """Render the pipeline outcome as a Rich panel."""
        mark = "[green]OK[/green]" if self.success else "[red]FAIL[/red]"
        body = (
            f"target_sha256: {self.target_sha256[:16]}...\n"
            f"target_kind:   {self.target_kind.value}\n"
            f"result:        {mark}\n"
        )
        if self.notes:
            body += "\n" + "\n".join(f"  - {n}" for n in self.notes)
        return Panel(body, title="Pipeline Run", border_style="green" if self.success else "red")


class Pipeline:
    """Single-pillar pipeline orchestrator (v1).

    Auto-detects target kind, constructs a GenericPythonStripper with the
    appropriate config, and runs it. The decompiler (pycdc / pylingual) is
    invoked as a subprocess — never imported as a Python module — to keep
    license posture clean (see 04_LEGAL_AND_SAFETY.md).

    Implementation status: STUB. The detect() method does a real sniff; the
    run() method returns a placeholder until the stripper stages are wired up.
    """

    def __init__(self, target: Path, out_dir: Path) -> None:
        self._target = target
        self._out_dir = out_dir

    def detect(self) -> TargetKind:
        """Sniff the target's first bytes to determine its kind.

        Implementation status: PARTIAL. Magic-byte matching is correct; the
        PyInstaller MEG cookie check is the well-known 'MEI\\014\\013\\012\\013\\016'
        at a known offset. The 4-byte .pyc magic numbers are well documented in
        CPython's importlib._bootstrap_external.
        """
        if not self._target.exists():
            raise FileNotFoundError(f"Target does not exist: {self._target}")

        suffix = self._target.suffix.lower()
        if suffix == ".py":
            return TargetKind.PY_SOURCE
        if suffix in {".pyc", ".pyo"}:
            return TargetKind.PYC_BYTECODE
        if suffix in {".exe", ""}:
            # Could be a PyInstaller bundle; sniff for the 'MEI\014\013\012\013\016' cookie
            with self._target.open("rb") as f:
                head = f.read(64)
            if b"MEI\014\013\012\013\016" in head:
                return TargetKind.PYINSTALLER_BUNDLE
        return TargetKind.UNKNOWN

    def run(self, on_progress: ProgressCallback) -> PipelineRunResult:
        """Run the single-pillar pipeline.

        v1 implementation: detect target kind, construct a
        GenericPythonStripper with kind-appropriate defaults, run it,
        wrap the stripper's PipelineResult in a PipelineRunResult.

        For TargetKind.PY_SOURCE, we run the stripper but expect unwrap
        to recover the source verbatim.  For .pyc, the decompile stage
        is the bottleneck (depends on whether pycdc is installed).
        """
        import time
        if not self._target.exists():
            raise FileNotFoundError(f"Target does not exist: {self._target}")

        target_hash = sha256_of_file(self._target)
        kind = self.detect()
        started = time.time()

        # v1 only ships one pillar: the generic Python stripper.
        # In v2 this is where .NET / PyArmor dispatch will go.
        from pyglimmer_toolkit.core.generic_python_stripper import (
            GenericPythonStripper, StripperConfig,
        )
        cfg = StripperConfig(
            target=self._target,
            out_dir=self._out_dir,
            allow_dis_fallback=False,  # production posture: no in-process fallback
        )
        stripper = GenericPythonStripper(cfg)
        stripper_result = stripper.run_pipeline(on_progress=on_progress)

        return PipelineRunResult(
            success=stripper_result.success,
            target_sha256=target_hash,
            target_kind=kind,
            stripper_result=stripper_result,
            duration_seconds=time.time() - started,
            notes=[f"delegated to GenericPythonStripper (v1 single-pillar)"],
        )
