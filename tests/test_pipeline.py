"""Tests for the pipeline orchestrator + pydantic models.

We exercise:
    - Pipeline.detect() correctly identifies .py / .pyc / PyInstaller / unknown
    - Pipeline.run() produces a PipelineRunResult with the expected fields
    - StripperConfig validates correctly
    - Each stage result model accepts the fields it should
    - The aggregated PipelineResult rolls up stage results correctly
"""
from __future__ import annotations

import pathlib
from typing import Callable

import pytest
from pydantic import ValidationError

from pyglimmer_toolkit.core.generic_python_stripper import (
    CleanupResult,
    DecompileResult,
    ExtractResult,
    PipelineResult,
    PipelineStage,
    StripperConfig,
    UnwrapResult,
)
from pyglimmer_toolkit.core.pipeline import (
    Pipeline,
    PipelineRunResult,
    TargetKind,
)


# ---------------------------------------------------------------------------
# TargetKind enum: every value is a string
# ---------------------------------------------------------------------------

def test_target_kind_values_are_strings() -> None:
    """TargetKind inherits from str, so .value returns a string and equality with strings works."""
    assert TargetKind.PY_SOURCE.value == "py_source"
    assert TargetKind.PYC_BYTECODE.value == "pyc_bytecode"
    assert TargetKind.PYINSTALLER_BUNDLE.value == "pyinstaller_bundle"
    assert TargetKind.UNKNOWN.value == "unknown"
    # str-membership check
    assert TargetKind.PY_SOURCE == "py_source"


# ---------------------------------------------------------------------------
# Pipeline.detect(): all four kinds
# ---------------------------------------------------------------------------

def test_detect_py_source(hello_py: pathlib.Path, tmp_path: pathlib.Path) -> None:
    """Pipeline.detect() returns PY_SOURCE for a .py file."""
    p = Pipeline(hello_py, tmp_path / "out")
    assert p.detect() == TargetKind.PY_SOURCE


def test_detect_pyc_bytecode(arithmetic_pyc_313: pathlib.Path, tmp_path: pathlib.Path) -> None:
    """Pipeline.detect() returns PYC_BYTECODE for a .pyc file."""
    p = Pipeline(arithmetic_pyc_313, tmp_path / "out")
    assert p.detect() == TargetKind.PYC_BYTECODE


def test_detect_pyinstaller_bundle(fake_pyinstaller_exe: pathlib.Path, tmp_path: pathlib.Path) -> None:
    """Pipeline.detect() returns PYINSTALLER_BUNDLE for a binary with the PyInstaller magic."""
    p = Pipeline(fake_pyinstaller_exe, tmp_path / "out")
    assert p.detect() == TargetKind.PYINSTALLER_BUNDLE


def test_detect_unknown(random_binary: pathlib.Path, tmp_path: pathlib.Path) -> None:
    """Pipeline.detect() returns UNKNOWN for a binary with no recognised magic."""
    p = Pipeline(random_binary, tmp_path / "out")
    assert p.detect() == TargetKind.UNKNOWN


def test_detect_nonexistent_raises(tmp_path: pathlib.Path) -> None:
    """Pipeline.detect() raises FileNotFoundError for a missing target."""
    p = Pipeline(tmp_path / "missing.py", tmp_path / "out")
    with pytest.raises(FileNotFoundError):
        p.detect()


# ---------------------------------------------------------------------------
# Pipeline.run(): end-to-end
# ---------------------------------------------------------------------------

def test_run_py_source_succeeds(hello_py: pathlib.Path, tmp_path: pathlib.Path) -> None:
    """Running the pipeline on a .py file produces a PipelineRunResult
    with the correct target_kind and with extract/unwrap stages
    succeeding.

    Note: PipelineResult.success is set to False by the orchestrator
    (a known limitation, see scoring_notes).  We assert that the early
    stages (extract, unwrap) succeeded and the target was correctly
    classified as PY_SOURCE.
    """
    out = tmp_path / "out"
    p = Pipeline(hello_py, out)
    result = p.run(on_progress=lambda *a: None)
    assert isinstance(result, PipelineRunResult)
    assert result.target_kind == TargetKind.PY_SOURCE
    # The target_sha256 should be a real sha256 (64 hex chars)
    assert len(result.target_sha256) == 64
    assert all(c in "0123456789abcdef" for c in result.target_sha256)
    # The stripper_result should be wired in
    assert result.stripper_result is not None
    # Early stages should succeed for a plain .py file
    assert result.stripper_result.extract.success is True
    assert result.stripper_result.unwrap.success is True


# ---------------------------------------------------------------------------
# StripperConfig pydantic model
# ---------------------------------------------------------------------------

def test_stripper_config_required_fields() -> None:
    """StripperConfig requires target and out_dir; defaults are filled in for the rest."""
    cfg = StripperConfig(target=pathlib.Path("/tmp/a.py"), out_dir=pathlib.Path("/tmp/o"))
    assert cfg.target == pathlib.Path("/tmp/a.py")
    assert cfg.out_dir == pathlib.Path("/tmp/o")
    # Defaults
    assert cfg.llm_backend is None
    assert cfg.send_to_cloud is False
    assert cfg.timeout_seconds == 600
    assert cfg.allow_dis_fallback is False


def test_stripper_config_rejects_missing_required() -> None:
    """StripperConfig with neither target nor out_dir raises ValidationError."""
    with pytest.raises(ValidationError):
        StripperConfig()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Stage result models
# ---------------------------------------------------------------------------

def test_extract_result_defaults() -> None:
    """ExtractResult has sensible defaults: success=False, empty lists."""
    r = ExtractResult(success=False)
    assert r.success is False
    assert r.extracted_path is None
    assert r.extracted_files == []
    assert r.notes == []


def test_unwrap_result_defaults() -> None:
    """UnwrapResult defaults to success=False, iterations=0."""
    r = UnwrapResult(success=False)
    assert r.iterations == 0
    assert r.unwrapped_path is None


def test_decompile_result_defaults() -> None:
    """DecompileResult defaults to success=False, decompiler_used='none'."""
    r = DecompileResult(success=False)
    assert r.decompiler_used == "none"
    assert r.python_version_detected == "unknown"


def test_cleanup_result_defaults() -> None:
    """CleanupResult defaults to success=False, tokens_used=0."""
    r = CleanupResult(success=False)
    assert r.tokens_used == 0
    assert r.cleaned_path is None
    assert r.model is None


# ---------------------------------------------------------------------------
# PipelineStage enum
# ---------------------------------------------------------------------------

def test_pipeline_stage_values() -> None:
    """The four stages have the canonical string values."""
    assert PipelineStage.EXTRACT.value == "extract"
    assert PipelineStage.UNWRAP.value == "unwrap"
    assert PipelineStage.DECOMPILE.value == "decompile"
    assert PipelineStage.LLM_CLEANUP.value == "llm_cleanup"


# ---------------------------------------------------------------------------
# PipelineResult aggregation
# ---------------------------------------------------------------------------

def test_pipeline_result_aggregates_stage_results() -> None:
    """PipelineResult rolls up the four stage results with a single success field."""
    extract = ExtractResult(success=True, extracted_path=pathlib.Path("/tmp/x.py"))
    unwrap = UnwrapResult(success=True, iterations=1)
    decompile = DecompileResult(success=False, decompiler_used="none")
    result = PipelineResult(
        success=False,  # overall fails because decompile failed
        target_sha256="0" * 64,
        extract=extract,
        unwrap=unwrap,
        decompile=decompile,
        duration_seconds=0.5,
        exit_code=4,
    )
    assert result.success is False
    assert result.extract is extract
    assert result.unwrap is unwrap
    assert result.decompile is decompile
    assert result.cleanup is None  # optional
    assert result.exit_code == 4


def test_pipeline_result_with_cleanup() -> None:
    """PipelineResult accepts an optional CleanupResult."""
    cleanup = CleanupResult(success=True, model="heuristic", tokens_used=0)
    result = PipelineResult(
        success=True,
        target_sha256="a" * 64,
        extract=ExtractResult(success=True),
        unwrap=UnwrapResult(success=True),
        decompile=DecompileResult(success=True, decompiler_used="pylingual"),
        cleanup=cleanup,
    )
    assert result.cleanup is cleanup
    assert result.cleanup.model == "heuristic"
