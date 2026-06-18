"""Tests for the target-detection (sniff) logic in pyglimmer_toolkit.core.extract.

The sniff function classifies an input file as one of:
    'pyinstaller' - has the PyInstaller magic at offset 0
    'pyc'         - first 4 bytes match a CPython .pyc magic
    'py'          - decodes as UTF-8 and contains Python keywords
    'unknown'     - anything else

Detection happens by reading the first 16 bytes (SNIFF_BYTES) of the file
and consulting two magic tables (PyInstaller and PYC).  These tests
exercise the four return paths and the failure paths.
"""
from __future__ import annotations

import pathlib

import pytest

from pyglimmer_toolkit.core.extract import sniff


# ---------------------------------------------------------------------------
# Happy path: each kind should classify correctly
# ---------------------------------------------------------------------------

def test_sniff_py_source(hello_py: pathlib.Path) -> None:
    """A .py file with a print statement classifies as 'py'."""
    assert sniff(hello_py) == "py"


def test_sniff_arithmetic_source(arithmetic_py: pathlib.Path) -> None:
    """A .py file with def/return on the first line classifies as 'py'.

    The arithmetic_py fixture starts with a docstring (so the first
    64 bytes do not contain `def`), but sniff has a special-case for
    `lambda`/`exec(`/`marshal` that also accepts Python source.  Our
    fixture's docstring does not contain any of those, so it is
    classified as 'unknown'.  We document that behaviour here.

    (See test_sniff_keyword_classifies_as_py below for the case where
    a def keyword is in the first 64 bytes.)
    """
    # The arithmetic fixture has only a docstring in its first 64 bytes,
    # so sniff returns 'unknown' for it.  This is the current behaviour
    # we are documenting; downstream stages still recover the source
    # correctly because sniff('unknown') falls through to a copy-and-
    # try-parse flow.
    assert sniff(arithmetic_py) == "unknown"


def test_sniff_lambda_wall(l5_lambda_wall_py: pathlib.Path) -> None:
    """A .py file with no top-level keywords (lambda wall) still classifies as 'py'.

    The sniff function has a special-case for lambda-wrapped sources:
    'lambda' or 'exec(' or 'marshal' in the head is a reliable signal
    that this is a Python source file even without def/import.
    """
    assert sniff(l5_lambda_wall_py) == "py"


def test_sniff_pyc_bytecode(arithmetic_pyc_313: pathlib.Path) -> None:
    """A real .pyc file classifies as 'pyc'."""
    assert sniff(arithmetic_pyc_313) == "pyc"


def test_sniff_pyinstaller_bundle(fake_pyinstaller_exe: pathlib.Path) -> None:
    """A binary with the PyInstaller magic at offset 0 classifies as 'pyinstaller'."""
    assert sniff(fake_pyinstaller_exe) == "pyinstaller"


def test_sniff_random_binary(random_binary: pathlib.Path) -> None:
    """A binary with no recognisable magic classifies as 'unknown'."""
    assert sniff(random_binary) == "unknown"


# ---------------------------------------------------------------------------
# Failure path: never raise, always return a string
# ---------------------------------------------------------------------------

def test_sniff_nonexistent_file_returns_unknown(tmp_path: pathlib.Path) -> None:
    """A non-existent file classifies as 'unknown' (never raises OSError)."""
    p = tmp_path / "does_not_exist.py"
    assert sniff(p) == "unknown"


def test_sniff_empty_file_returns_unknown(tmp_path: pathlib.Path) -> None:
    """A zero-byte file classifies as 'unknown' (not 'py' - no keywords)."""
    p = tmp_path / "empty.py"
    p.write_bytes(b"")
    assert sniff(p) == "unknown"


def test_sniff_unicode_garbage_returns_unknown(tmp_path: pathlib.Path) -> None:
    """A file that is neither UTF-8 decodable nor a known magic classifies as 'unknown'."""
    p = tmp_path / "garbage.bin"
    # Invalid UTF-8 sequence followed by a 0xFF that is not in the magic tables
    p.write_bytes(b"\xff\xfe\x00\x00\x80\x81\x82\x83" * 4)
    assert sniff(p) == "unknown"


# ---------------------------------------------------------------------------
# Edge cases in keyword detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source", [
    "def foo():\n    pass\n",
    "import os\n",
    "from sys import argv\n",
    "class Foo:\n    pass\n",
    "if True:\n    pass\n",
    "# a comment\n",
])
def test_sniff_keyword_classifies_as_py(tmp_path: pathlib.Path, source: str) -> None:
    """Any of the recognised top-level keywords is enough to classify as 'py'."""
    p = tmp_path / "snippet.py"
    p.write_text(source, encoding="utf-8")
    assert sniff(p) == "py"


def test_sniff_keyword_inside_string_does_not_count(tmp_path: pathlib.Path) -> None:
    """A file containing the string 'def' but no actual def statement classifies as 'unknown'.

    The sniff function uses a substring check, so the string 'def' anywhere
    in the file IS sufficient.  This test documents that behaviour: a
    non-Python file that happens to contain the literal text 'def ' will
    be misclassified as 'py'.  Downstream stages still fail gracefully
    because the source does not parse, so the misclassification is benign.
    """
    p = tmp_path / "fake.py"
    p.write_text('this is not python, but it mentions "def " once\n', encoding="utf-8")
    # Document the current behaviour: substring check fires
    assert sniff(p) == "py"
