"""Generic Python obfuscation stripper.

The single v1 pillar of pyglimmer-stripper. See `05_ADVERSARIAL_REVIEW.md` for
why the .NET sidecar and PyArmor wrap were dropped from v1.

Pipeline:
    0. Raw target (.py, .pyc, or PyInstaller bundle)
    1. Extract (PyInstaller -> folder of .pyc; .pyc -> readable bytes; .py -> text)
    2. Unwrap (base64/marshal/lambda layers removed iteratively until AST-parseable)
    3. Decompile (route to pycdc for <=3.10, pylingual for >=3.11)
    4. LLM cleanup (optional; Ollama default, Anthropic/OpenAI opt-in)

The LLM cleanup pass is the genuine differentiator — no public stable tool ships
this as of 2026-06-17 (see 06_VERIFIED_FACTS.md, F-15).

Architecture:
    - State machine: extract -> unwrap -> decompile -> (optional) llm_cleanup
    - Resumable: per-target `.pyglimmer_cache/<sha>/state.json` survives crashes
    - Cross-platform: pure Python orchestration, subprocess CLI invocations
    - Subprocess-only decompiler integration (avoid module-import license entanglement)

References:
    https://github.com/syssec-utd/pylingual
    https://github.com/zrax/pycdc
    https://github.com/extremecoders-re/pyinstxtractor
"""

from __future__ import annotations

import shutil
import sys
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from pydantic import BaseModel, Field
from rich.console import Console

from pyglimmer_toolkit.utils.hashing import sha256_of_file

console = Console(stderr=True)

ProgressCallback = Callable[[float, str], None]


class PipelineStage(str, Enum):
    """The four pipeline stages."""

    EXTRACT = "extract"
    UNWRAP = "unwrap"
    DECOMPILE = "decompile"
    LLM_CLEANUP = "llm_cleanup"


class StripperConfig(BaseModel):
    """Inputs to a stripper job."""

    target: Path
    out_dir: Path
    llm_backend: Optional[str] = None  # "ollama::14b", "anthropic", "openai"
    send_to_cloud: bool = False  # Hard gate - must be True to use Anthropic/OpenAI
    timeout_seconds: int = 600
    # Optional user-supplied paths to keep the project off the § 1201 / static-link
    # GPL entanglements. See 04_LEGAL_AND_SAFETY.md.
    decompiler_path: Optional[Path] = None  # directory containing pycdc binary
    pylingual_model_path: Optional[Path] = None  # local pylingual model dir
    pyinstxtractor_path: Optional[Path] = None  # pyinstxtractor.py (for .exe input)
    # Dev-only: allow a structural dis-based fallback when neither pycdc
    # nor pylingual is available.  Not for production use; produces
    # incomplete source for non-trivial bytecode.  See core/decompile.py.
    allow_dis_fallback: bool = False


class ExtractResult(BaseModel):
    """Result of the EXTRACT stage."""

    success: bool
    extracted_path: Optional[Path] = None
    extracted_files: list[Path] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class UnwrapResult(BaseModel):
    """Result of the UNWRAP stage."""

    success: bool
    iterations: int = 0
    unwrapped_path: Optional[Path] = None
    notes: list[str] = Field(default_factory=list)


class DecompileResult(BaseModel):
    """Result of the DECOMPILE stage."""

    success: bool
    decompiler_used: str = "none"  # "pycdc" | "pylingual" | "uncompyle6" | "none"
    decompiled_path: Optional[Path] = None
    python_version_detected: str = "unknown"
    notes: list[str] = Field(default_factory=list)


class CleanupResult(BaseModel):
    """Result of the optional LLM CLEANUP stage."""

    success: bool
    model: Optional[str] = None
    cleaned_path: Optional[Path] = None
    tokens_used: int = 0
    notes: list[str] = Field(default_factory=list)


class PipelineResult(BaseModel):
    """Top-level pipeline result: aggregates all four stage results."""

    success: bool
    target_sha256: str
    extract: ExtractResult
    unwrap: UnwrapResult
    decompile: DecompileResult
    cleanup: Optional[CleanupResult] = None
    duration_seconds: float = 0.0
    exit_code: int = 0  # 0 ok, 2 extract-failed, 3 unwrap-failed, 4 decompile-failed

    def summary_panel(self):
        """Render a Rich panel summarizing the full pipeline outcome."""
        from rich.panel import Panel

        lines = [
            f"target_sha256: {self.target_sha256[:16]}...",
            f"extract: {'OK' if self.extract.success else 'FAIL'}",
            f"unwrap:  {'OK' if self.unwrap.success else 'FAIL'} ({self.unwrap.iterations} iters)",
            f"decompile: {'OK' if self.decompile.success else 'FAIL'} ({self.decompile.decompiler_used})",
        ]
        if self.cleanup is not None:
            lines.append(
                f"llm_cleanup: {'OK' if self.cleanup.success else 'FAIL'} ({self.cleanup.model})"
            )
        body = "\n".join(lines)
        return Panel(
            body,
            title="Python Stripper Pipeline",
            border_style="green" if self.success else "red",
        )


class GenericPythonStripper:
    """Orchestrates the four-stage Python-stripper pipeline.

    Implementation status: STUB. All stage methods return placeholder results
    until the upstream CLI integrations are wired up.
    """

    def __init__(self, config: StripperConfig) -> None:
        self._config = config

    def extract(self) -> ExtractResult:
        """EXTRACT stage.

        Routes the target to one of three handlers based on sniff() output:
            - 'pyinstaller' -> pyinstxtractor (user-supplied)
            - 'pyc'         -> copy + record Python version
            - 'py'          -> passthrough copy
        """
        from pyglimmer_toolkit.core.extract import (
            extract_py,
            extract_pyc,
            extract_pyinstaller,
            sniff,
        )

        target = self._config.target
        notes: list[str] = []
        kind = sniff(target)
        out_dir = self._config.out_dir / "extracted"

        if kind == "pyinstaller":
            extracted_path, extracted_files = extract_pyinstaller(
                target, out_dir, self._config.pyinstxtractor_path, notes
            )
        elif kind == "pyc":
            extracted_path, extracted_files = extract_pyc(target, out_dir, notes)
        elif kind == "py":
            extracted_path, extracted_files = extract_py(target, out_dir, notes)
        else:
            return ExtractResult(
                success=False,
                notes=[f"unrecognized target: {target} (sniff returned '{kind}')"],
            )

        success = extracted_path is not None
        return ExtractResult(
            success=success,
            extracted_path=extracted_path,
            extracted_files=extracted_files,
            notes=notes,
        )

    def unwrap(self, extracted: ExtractResult) -> UnwrapResult:
        """UNWRAP stage.

        Iteratively peel obfuscation layers off the extracted source until
        stable. L1 (base64) and L5 (lambda wall) recover to text; L2/L3
        (marshal variants) hand off to Stage 4 via a code-object marker.
        """
        from pyglimmer_toolkit.core.unwrap import unwrap_file

        if not extracted.success or extracted.extracted_path is None:
            return UnwrapResult(
                success=False,
                notes=["unwrap: nothing to unwrap (extract failed or no path)"],
            )

        extracted_path = extracted.extracted_path
        notes: list = []

        # If extract produced a single .py file, unwrap it.  If it produced
        # a folder (PyInstaller bundle), unwrap each .pyc inside it and
        # leave a note.  We don't try to merge multi-file results here -
        # the v1 test bench only ever produces a single file per case.
        if extracted_path.is_file():
            out_dir = self._config.out_dir / "unwrapped"
            unwrapped_path, file_notes, iterations = unwrap_file(extracted_path, out_dir)
            notes.extend(file_notes)
        elif extracted_path.is_dir():
            out_dir = self._config.out_dir / "unwrapped"
            out_dir.mkdir(parents=True, exist_ok=True)
            py_files = list(extracted_path.rglob("*.py"))
            unwrapped_path = out_dir
            iterations = 0
            for p in py_files:
                _, n_it, _ = unwrap_file(p, out_dir)
                iterations += n_it
            pyc_files = list(extracted_path.rglob("*.pyc"))
            for p in pyc_files:
                shutil.copy2(p, out_dir / p.name)
                notes.append(f"copied .pyc (decompile-stage input): {p.name}")
        else:
            return UnwrapResult(
                success=False,
                notes=[f"unwrap: extracted path is neither file nor dir: {extracted_path}"],
            )

        return UnwrapResult(
            success=True,
            iterations=iterations,
            unwrapped_path=unwrapped_path,
            notes=notes,
        )

    def decompile(self, unwrapped: UnwrapResult) -> DecompileResult:
        """DECOMPILE stage.

        Hand the unwrapped output to ``core.decompile.decompile_file``,
        which routes to pycdc (Python <=3.10) or pylingual (>=3.11) via
        subprocess.  A dev-only ``dis``-based structural fallback is
        available behind ``StripperConfig.allow_dis_fallback`` so the
        test bench can score L6 cases without requiring pycdc or a
        pylingual model to be installed.
        """
        from pyglimmer_toolkit.core import decompile as _decompile

        if unwrapped.unwrapped_path is None or not unwrapped.unwrapped_path.exists():
            return DecompileResult(
                success=False,
                notes=["decompile: unwrap produced no path; nothing to decompile"],
            )

        # Build the pylingual command.  We shell out to ``pylingual`` (which
        # must be on PATH, e.g. via ``uv tool install pylingual``).  We
        # pass ``--quiet`` to suppress rich console output, which
        # crashes on cp1252 Windows consoles.  The model is auto-resolved
        # from pylingual's bundled decompiler_config.yaml which points
        # at the HuggingFace model repos.
        pylingual_cmd = None
        if self._config.pylingual_model_path is not None:
            pylingual_cmd = ["pylingual", "--quiet"]

        # Build the pycdc exe path.  We accept either a directory (we
        # append the conventional binary name) or an explicit file path.
        pycdc_exe = None
        if self._config.decompiler_path is not None:
            if self._config.decompiler_path.is_dir():
                candidate = self._config.decompiler_path / ("pycdc.exe" if sys.platform == "win32" else "pycdc")
                if candidate.exists():
                    pycdc_exe = candidate
            elif self._config.decompiler_path.is_file():
                pycdc_exe = self._config.decompiler_path

        decompile_out_dir = self._config.out_dir / "decompiled"
        decompiled_path, backend, pyver = _decompile.decompile_file(
            input_path=unwrapped.unwrapped_path,
            out_dir=decompile_out_dir,
            pycdc_exe=pycdc_exe,
            pylingual_cmd=pylingual_cmd,
            allow_dis_fallback=self._config.allow_dis_fallback,
        )

        if backend == "none":
            return DecompileResult(
                success=False,
                decompiler_used="none",
                python_version_detected=pyver,
                notes=[
                    f"decompile: no backend succeeded for {unwrapped.unwrapped_path.name}",
                    f"  Wrote placeholder to {decompiled_path}",
                ],
            )

        return DecompileResult(
            success=True,
            decompiler_used=backend,
            decompiled_path=decompiled_path,
            python_version_detected=pyver,
            notes=[f"decompile: {backend} recovered source from {unwrapped.unwrapped_path.name}"],
        )

    def llm_cleanup(
        self,
        decompiled_result: DecompileResult,
        model: Callable[[str], str],
        on_progress: ProgressCallback,
    ) -> CleanupResult:
        """LLM CLEANUP stage.

        Hand the decompiled source to ``core.cleanup.llm_cleanup_file``
        and let it dispatch to the configured backend.  When no
        `model` callable is supplied we still go through the
        default-Ollama path, which gracefully no-ops if no local
        server is running.  Cloud backends (anthropic/openai) require
        ``send_to_cloud=True`` in StripperConfig.
        """
        from pyglimmer_toolkit.core import cleanup as _cleanup

        if decompiled_result.decompiled_path is None or not decompiled_result.decompiled_path.exists():
            return CleanupResult(
                success=False,
                notes=["llm_cleanup: decompile produced no path; nothing to clean"],
            )

        # Parse the configured backend out of llm_backend.  We accept
        # formats like "ollama:14b", "ollama::14b", "anthropic:opus",
        # "openai:gpt-4o", or bare "ollama".
        backend = "ollama"
        model_name = ".5-coder:14b"  # a reasonable default for code cleanup
        if self._config.llm_backend:
            parts = self._config.llm_backend.split(":", 1)
            backend = parts[0] or "ollama"
            if len(parts) == 2 and parts[1]:
                model_name = parts[1].lstrip(":") or model_name

        cleanup_out_dir = self._config.out_dir / "cleaned"
        cleaned_path, changed, tokens, message = _cleanup.llm_cleanup_file(
            input_path=decompiled_result.decompiled_path,
            out_dir=cleanup_out_dir,
            model_fn=model,
            backend=backend,
            model_name=model_name,
            send_to_cloud=self._config.send_to_cloud,
            timeout=self._config.timeout_seconds,
        )

        return CleanupResult(
            success=True,
            model=f"{backend}:{model_name}",
            cleaned_path=cleaned_path,
            tokens_used=tokens,
            notes=[message, f"  cleaned path: {cleaned_path}", f"  changed: {changed}"],
        )

    def run_pipeline(self, on_progress: ProgressCallback) -> PipelineResult:
        """Top-level: run EXTRACT -> UNWRAP -> DECOMPILE -> (optional) LLM_CLEANUP.

        Implementation status: STUB-ORCHESTRATOR. Each stage is its own stub;
        once they're implemented this orchestrator just chains them and writes
        `.pyglimmer_cache/<sha>/state.json` after each stage for resumability.
        """
        target = self._config.target
        if not target.exists():
            raise FileNotFoundError(f"Target does not exist: {target}")

        target_hash = sha256_of_file(target)
        on_progress(0.0, "STUB: pipeline orchestrator")

        extract_result = self.extract()
        on_progress(0.25, "STUB: extract done")
        unwrap_result = self.unwrap(extract_result)
        on_progress(0.50, "STUB: unwrap done")
        decompile_result = self.decompile(unwrap_result)
        on_progress(0.75, "STUB: decompile done")

        cleanup_result: Optional[CleanupResult] = None
        if self._config.llm_backend is not None:
            # In the real impl, `model` is a callable wrapping the LLM client.
            cleanup_result = self.llm_cleanup(
                decompiled_result=decompile_result,
                model=lambda src: "(STUB) cleaned output",
                on_progress=on_progress,
            )
            on_progress(1.0, "STUB: llm_cleanup done")

        return PipelineResult(
            success=False,
            target_sha256=target_hash,
            extract=extract_result,
            unwrap=unwrap_result,
            decompile=decompile_result,
            cleanup=cleanup_result,
        )
