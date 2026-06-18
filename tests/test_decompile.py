"""Tests for the DECOMPILE stage (pyglimmer_toolkit.core.decompile).

The decompile stage has three backends:
    1. pycdc   - subprocess to the pycdc binary, handles <=3.10
    2. pylingual - subprocess to pylingual, handles 3.11+
    3. dis-fallback - in-process dis-based unparser, dev only

Routing is by Python version (detected from the .pyc header magic).  These
tests verify the routing logic, the magic-number detection, the
in-process dis-fallback output, and the failure paths (no decompiler
installed, missing pycdc binary, etc.).
"""
from __future__ import annotations

import pathlib

import pytest

from pyglimmer_toolkit.core.decompile import (
    MAGIC_NUMBERS,
    detect_python_version,
    decompile_file,
    decompile_with_dis,
)


# ---------------------------------------------------------------------------
# Magic-number table and detection
# ---------------------------------------------------------------------------

def test_magic_numbers_table_covers_3_6_through_3_14() -> None:
    """The MAGIC_NUMBERS dict should cover at least the range 3.6-3.14."""
    versions = set(MAGIC_NUMBERS.values())
    expected = {"3.6", "3.7", "3.8", "3.9", "3.10", "3.11", "3.12", "3.13", "3.14"}
    # The table is allowed to be a subset of these, but should at least
    # cover the documented v1 routing range
    assert expected.issubset(versions), f"missing versions: {expected - versions}"


def test_magic_numbers_values_are_distinct() -> None:
    """Each magic number maps to exactly one Python version."""
    assert len(MAGIC_NUMBERS) == len(set(MAGIC_NUMBERS.values()))


def test_detect_python_version_on_real_pyc(arithmetic_pyc_313: pathlib.Path) -> None:
    """detect_python_version on a .pyc built by the current interpreter returns its version."""
    v = detect_python_version(arithmetic_pyc_313)
    # The pyc was built under the current interpreter (3.14 in .venv314)
    # The detection should return *something*; the exact version depends on
    # the interpreter that built it
    assert v in MAGIC_NUMBERS.values()
    assert v != "unknown"


def test_detect_python_version_on_non_pyc(tmp_path: pathlib.Path) -> None:
    """detect_python_version on a non-pyc file returns 'unknown' (does not crash)."""
    p = tmp_path / "garbage.bin"
    p.write_bytes(b"this is not a pyc file, just text\n")
    v = detect_python_version(p)
    assert v == "unknown"


# ---------------------------------------------------------------------------
# dis-fallback: in-process, deterministic, no subprocess
# ---------------------------------------------------------------------------

def test_dis_fallback_writes_a_file(arithmetic_pyc_313: pathlib.Path, tmp_path: pathlib.Path) -> None:
    """decompile_with_dis writes a .py file even for the simplest bytecode."""
    out = tmp_path / "dis_out.py"
    ok, msg = decompile_with_dis(arithmetic_pyc_313, out)
    assert ok is True
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    # dis-fallback at minimum emits a header
    assert "Decompiled by pyglimmer dis-fallback" in text
    # And it should mention `main` (the function in the arithmetic source)
    assert "main" in text


# ---------------------------------------------------------------------------
# decompile_file: high-level routing
# ---------------------------------------------------------------------------

def test_decompile_file_with_marker_input_uses_dis_fallback(
    l2_marshal_marker: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """decompile_file on a marker .py file uses the dis-fallback path.

    We pass allow_dis_fallback=True and no pycdc / pylingual.  The
    result is a placeholder .py file with the dis-fallback's known
    defect (f\"((expr))\") for the arithmetic case.  We only assert
    that the file is written and contains the dis-fallback header.

    The input must be a *marker* file (a # __SigilCodeObjectMarker__
    line), not the L2 wrapper.  decompile_file reads the code object
    out of the marker, writes it to a temp .pyc, and routes to a
    decompiler.
    """
    out_dir = tmp_path / "out"
    out_path, backend, version = decompile_file(
        l2_marshal_marker, out_dir, allow_dis_fallback=True,
    )
    assert out_path.exists()
    assert backend == "dis-fallback"  # the canonical name uses a dash
    text = out_path.read_text(encoding="utf-8")
    # dis-fallback header is present
    assert "Decompiled by pyglimmer dis-fallback" in text
    # The function name is preserved
    assert "main" in text


def test_decompile_file_with_real_pyc_routes_to_dis_fallback(
    arithmetic_pyc_313: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """decompile_file on a real .pyc with no external decompiler falls back to dis."""
    out_dir = tmp_path / "out"
    out_path, backend, version = decompile_file(
        arithmetic_pyc_313, out_dir, allow_dis_fallback=True,
    )
    assert out_path.exists()
    assert backend == "dis-fallback"
    assert version in MAGIC_NUMBERS.values()


def test_decompile_file_creates_out_dir(
    l2_marshal_py: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """decompile_file creates out_dir if it does not exist (no FileNotFoundError)."""
    out_dir = tmp_path / "does_not_exist_yet" / "out"
    out_path, backend, version = decompile_file(
        l2_marshal_py, out_dir, allow_dis_fallback=True,
    )
    assert out_dir.exists()
    assert out_path.exists()


# ---------------------------------------------------------------------------
# Routing decisions: 3.10 routes to pycdc first, 3.11+ to pylingual
# ---------------------------------------------------------------------------

def test_routing_pycdc_first_for_3_10(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """For a 3.10 .pyc, the routing logic tries pycdc before pylingual.

    We monkeypatch decompile_with_pycdc to a spy that records the call,
    and verify the spy was invoked.  pylingual is NOT called in this
    path (because pycdc returned a result).

    decompile_with_pycdc returns (ok: bool, msg: str), and the wrapper
    in decompile_file translates that into a 3-tuple (path, backend, ver).
    """
    from pyglimmer_toolkit.core import decompile as decomp_mod

    pycdc_called = []

    def fake_pycdc(pyc_path, out_path, pycdc_exe, **kwargs):
        pycdc_called.append(pyc_path)
        # Pretend pycdc successfully wrote the decompiled source to out_path
        out_path.write_text("# decompiled by pycdc\n", encoding="utf-8")
        return (True, "ok")

    def fake_pylingual(*args, **kwargs):
        raise AssertionError("pylingual should not be called when pycdc succeeds")

    # Build a fake 3.10 .pyc (just the magic + dummy payload)
    import struct
    pyc = tmp_path / "fake_3_10.pyc"
    pyc.write_bytes(b"\x6e\x0d\x0d\x0a" + struct.pack("<III", 0, 0, 1) + b"\x00" * 16)

    monkeypatch.setattr(decomp_mod, "decompile_with_pycdc", fake_pycdc)
    monkeypatch.setattr(decomp_mod, "decompile_with_pylingual", fake_pylingual)

    out_dir = tmp_path / "out"
    out_path, backend, version = decompile_file(
        pyc, out_dir, pycdc_exe=tmp_path / "fake_pycdc.exe",
        allow_dis_fallback=False,
    )
    assert pycdc_called, "pycdc was not called for 3.10 .pyc"
    assert backend == "pycdc"
    assert version == "3.10"


def test_routing_pylingual_first_for_3_14(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """For a 3.14 .pyc, the routing logic tries pylingual first (and pycdc only as fallback)."""
    from pyglimmer_toolkit.core import decompile as decomp_mod

    pylingual_called = []
    pycdc_called = []

    def fake_pylingual(pyc_path, out_path, pylingual_cmd, **kwargs):
        pylingual_called.append(pyc_path)
        out_path.write_text("# decompiled by pylingual\n", encoding="utf-8")
        return (True, "ok")

    def fake_pycdc(*args, **kwargs):
        pycdc_called.append(True)
        return (False, "should not be called")

    import struct
    pyc = tmp_path / "fake_3_14.pyc"
    pyc.write_bytes(b"\x2c\x0e\x0d\x0a" + struct.pack("<III", 0, 0, 1) + b"\x00" * 16)

    monkeypatch.setattr(decomp_mod, "decompile_with_pylingual", fake_pylingual)
    monkeypatch.setattr(decomp_mod, "decompile_with_pycdc", fake_pycdc)

    out_dir = tmp_path / "out"
    out_path, backend, version = decompile_file(
        pyc, out_dir, pylingual_cmd=["pylingual"],
        allow_dis_fallback=False,
    )
    assert pylingual_called, "pylingual was not called for 3.14 .pyc"
    assert not pycdc_called, "pycdc was called for 3.14 .pyc (should be pylingual-only)"
    assert backend == "pylingual"
    assert version == "3.14"


# ---------------------------------------------------------------------------
# Failure path: no decompiler, no fallback - should write a placeholder, not crash
# ---------------------------------------------------------------------------

def test_decompile_file_no_decompiler_writes_placeholder(
    l2_marshal_py: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """decompile_file with no decompiler and allow_dis_fallback=False writes a placeholder."""
    out_dir = tmp_path / "out"
    out_path, backend, version = decompile_file(
        l2_marshal_py, out_dir,
        pycdc_exe=None, pylingual_cmd=None, allow_dis_fallback=False,
    )
    # File is written (a placeholder, not a real decompilation)
    assert out_path.exists()
    # Either it is a dis_fallback (because we allowed it) OR a placeholder
    # with a "no decompiler" message
    text = out_path.read_text(encoding="utf-8")
    # At minimum, the file is a .py file with *some* content
    assert len(text) > 0
