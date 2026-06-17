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
    send_to_cloud: bool = False  # Hard gate — must be True to use Anthropic/OpenAI
    timeout_seconds: int = 600
    # Optional user-supplied paths to keep the project off the § 1201 / static-link
    # GPL entanglements. See 04_LEGAL_AND_SAFETY.md.
    decompiler_path: Optional[Path] = None  # directory containing pycdc binary
    pylingual_model_path: Optional[Path] = None  # local pylingual model dir


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

        Stub. The real implementation will:
            1. Sniff the target's first 4 bytes.
            2. PyInstaller bundle (MAGIC at offset 0x00 + 'MEI\\014\\013\\012\\013\\016') ->
               shell out to pyinstxtractor (extremecoders-re/pyinstxtractor).
            3. .pyc -> parse magic number, validate header, return bytes path.
            4. .py -> copy to extracted_path.
        """
        return ExtractResult(
            success=False,
            notes=[
                "STUB: extract not implemented. "
                "See 03_FEATURE_FEASIBILITY.md -> Generic Python Stripping Specialist Deep-Dive."
            ],
        )

    def unwrap(self, extracted: ExtractResult) -> UnwrapResult:
        """UNWRAP stage.

        Stub. The real implementation will:
            1. Read the extracted file/folder.
            2. Iteratively: parse AST -> find exec(base64/marshal/zlib) -> evaluate
               the literal -> replace -> re-parse.
            3. Stop when AST is stable OR no more unwrappable patterns.
            4. Write the unwrapped form to unwrapped_path.
        """
        return UnwrapResult(
            success=False,
            notes=[
                "STUB: unwrap not implemented. "
                "See 03_FEATURE_FEASIBILITY.md -> Generic Python Stripping Specialist Deep-Dive."
            ],
        )

    def decompile(self, unwrapped: UnwrapResult) -> DecompileResult:
        """DECOMPILE stage.

        Stub. The real implementation will:
            1. Read the unwrapped bytecode (.pyc).
            2. Detect the Python version from the magic number.
            3. Route to pycdc (<=3.10) or pylingual (>=3.11), both as subprocesses.
            4. Return the decompiled source path.
        """
        return DecompileResult(
            success=False,
            notes=[
                "STUB: decompile not implemented. "
                "See 03_FEATURE_FEASIBILITY.md -> Generic Python Stripping Specialist Deep-Dive."
            ],
        )

    def llm_cleanup(
        self,
        decompiled_result: DecompileResult,
        model: Callable[[str], str],
        on_progress: ProgressCallback,
    ) -> CleanupResult:
        """LLM CLEANUP stage.

        Stub. The real implementation will:
            1. Verify the LLM backend (cloud requires self._config.send_to_cloud=True).
            2. Read the decompiled source.
            3. Send the cleanup prompt + source to the model.
            4. Stream the response; on_progress called per token.
            5. Run `_semantic_diff` (AST-based) to verify the cleanup didn't break semantics.
            6. Write to cleaned_path.
        """
        return CleanupResult(
            success=False,
            notes=[
                "STUB: llm_cleanup not implemented. "
                "See 03_FEATURE_FEASIBILITY.md -> Generic Python Stripping Specialist Deep-Dive."
            ],
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
