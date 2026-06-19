"""Tests for the EXTRACT stage on PyInstaller bundles (P2-6).

We build a synthetic 100-byte fake PyInstaller bundle with the
canonical `MEI\014\013\012\013\016` magic cookie and verify the
sniff / detect / extract chain treats it as a PyInstaller bundle.

A real PyInstaller .exe is too large to commit (~10 MB minimum); we
use the synthetic fixture instead.  The test verifies the *detection*
path is correct; the actual extraction via pyinstxtractor.py is a
runtime concern (pyinstxtractor is a user-supplied script, not
vendored).

The PyInstaller binary format (briefly):
    [bootloader prefix: ~32 KB of native code]
    [MAGIC cookie: b"MEI\\014\\013\\012\\013\\016" — 8 bytes]
    [python search path strings]
    [COOKIE struct: TOC, version, etc.]

The sniffer only looks for the MAGIC in the first 64 bytes of the
file, so a 100-byte fixture is sufficient for the sniff test.
"""
from __future__ import annotations

import pathlib

import pytest

from pyglimmer_toolkit.core.extract import (
    PYINSTALLER_MAGIC,
    extract_pyinstaller,
    sniff,
)
from pyglimmer_toolkit.core.pipeline import Pipeline, TargetKind


PYINSTALLER_MAGIC_BYTES = b"MEI\014\013\012\013\016"


def make_pyinstaller_fixture(work_dir: pathlib.Path) -> pathlib.Path:
    """Build a 100-byte fake PyInstaller bundle with the MEI magic.

    The fixture is *not* a real executable — it has the canonical
    magic cookie but no valid bootloader or TOC.  That's enough to
    trigger the sniffer's PyInstaller detection path, which is what
    these tests exercise.
    """
    fixture = work_dir / "fake.exe"
    bootloader = b"\x00" * 32          # 32 bytes of fake bootloader
    magic = PYINSTALLER_MAGIC_BYTES     # 8 bytes
    cookie = b"\x00" * 24              # 24 bytes of fake COOKIE struct
    padding = b"\x00" * (100 - len(bootloader) - len(magic) - len(cookie))
    fixture.write_bytes(bootloader + magic + cookie + padding)
    assert fixture.stat().st_size == 100
    return fixture


# ---------------------------------------------------------------------------
# Sniff: returns "pyinstaller" for fixtures with the MEI magic
# ---------------------------------------------------------------------------

def test_sniff_pyinstaller_magic(tmp_path: pathlib.Path) -> None:
    """sniff() on a file with the MEI magic returns 'pyinstaller'."""
    fixture = make_pyinstaller_fixture(tmp_path)
    assert sniff(fixture) == "pyinstaller"


def test_sniff_does_not_return_pyinstaller_without_magic(tmp_path: pathlib.Path) -> None:
    """sniff() on a file *without* the MEI magic does NOT return 'pyinstaller'.

    Sanity check: the magic must be present for the sniffer to fire.
    """
    fixture = tmp_path / "no_magic.bin"
    fixture.write_bytes(b"\x00" * 64)
    assert sniff(fixture) != "pyinstaller"


def test_pyinstaller_magic_constant_is_canonical() -> None:
    """The PYINSTALLER_MAGIC constant must be exactly b'MEI\\014\\013\\012\\013\\016'.

    If this assertion fails, our synthetic fixture won't match the
    sniffer and the whole test suite goes red.  Pin it.
    """
    assert PYINSTALLER_MAGIC == b"MEI\014\013\012\013\016"
    assert len(PYINSTALLER_MAGIC) == 8


# ---------------------------------------------------------------------------
# Pipeline.detect: classifies a PyInstaller bundle as PYINSTALLER_BUNDLE
# ---------------------------------------------------------------------------

def test_pipeline_detect_pyinstaller(tmp_path: pathlib.Path) -> None:
    """Pipeline.detect() returns TargetKind.PYINSTALLER_BUNDLE for our fixture."""
    fixture = make_pyinstaller_fixture(tmp_path)
    out_dir = tmp_path / "out"
    pipeline = Pipeline(target=fixture, out_dir=out_dir)
    assert pipeline.detect() == TargetKind.PYINSTALLER_BUNDLE


# ---------------------------------------------------------------------------
# extract_pyinstaller: returns (None, []) when pyinstxtractor is not supplied
# ---------------------------------------------------------------------------

def test_extract_pyinstaller_without_pyinstxtractor_returns_none(
    tmp_path: pathlib.Path,
) -> None:
    """extract_pyinstaller with no pyinstxtractor_path returns (None, []).

    This is the documented behavior: we don't bundle pyinstxtractor;
    users supply it themselves.  The test confirms we don't silently
    fabricate output when the tool is missing.
    """
    fixture = make_pyinstaller_fixture(tmp_path)
    out_dir = tmp_path / "out"
    notes: list = []
    result, paths = extract_pyinstaller(
        target=fixture,
        out_dir=out_dir,
        pyinstxtractor_path=None,
        notes=notes,
    )
    assert result is None
    assert paths == []
    assert any("pyinstxtractor" in n.lower() for n in notes), (
        f"notes should mention pyinstxtractor; got {notes!r}"
    )
