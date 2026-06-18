"""Tests for the UNWRAP stage (pyglimmer_toolkit.core.unwrap).

The unwrap stage peels obfuscation layers off a recovered source file.
Each layer has a regex detector:

    L1 (base64)        - one-shot base64-wrapped source
    L2 (marshal)       - marshal.dumps(code) inside a base64 marker
    L3 (zlib+marshal)  - zlib.compress(marshal.dumps(code)) inside a marker
    L5 (lambda wall)   - (lambda: (lambda: ...)())() chain

These tests cover the L1 and L5 paths in isolation (round-trip: wrap
source, unwrap, check the result equals the original).  L2 and L3 are
tested through the higher-level stripper because the round-trip is
harder to verify directly (marshal.dumps loses the original bytecodes
under 3.14).
"""
from __future__ import annotations

import base64
import marshal
import pathlib

import pytest

from pyglimmer_toolkit.core import unwrap as unwrap_mod
from pyglimmer_toolkit.core.unwrap import unwrap_iter, unwrap_once, code_object_from_marker


# ---------------------------------------------------------------------------
# L1: base64 unwrap recovers the original source verbatim
# ---------------------------------------------------------------------------

def test_unwrap_l1_base64_recovers_source(tmp_path: pathlib.Path) -> None:
    """L1 base64 wrapper unwraps to the original source string.

    The L1 regex requires `exec(base64.b64decode(<b64>).decode("utf-8"))`
    — the `.decode("utf-8")` suffix is mandatory.  The eval/obfuscate.py
    generator produces this exact shape.
    """
    original = 'def main():\n    return "hello world"\n'
    payload = base64.b64encode(original.encode("utf-8")).decode("ascii")
    wrapped = f'import base64\nexec(base64.b64decode("{payload}").decode("utf-8"))\n'
    notes: list[str] = []

    out = unwrap_once(wrapped, notes)

    assert out == original
    assert any("L1" in n for n in notes)


def test_unwrap_l1_iteration_in_stripped_text() -> None:
    """An L1-wrapped source unwraps cleanly through unwrap_iter.

    The L1 regex requires `import base64` at the start of a line, so
    no leading comment is allowed.  We use the bare wrapper and verify
    that unwrap_iter peels it in one call.
    """
    original = 'def main():\n    return "hello world"\n'
    payload = base64.b64encode(original.encode("utf-8")).decode("ascii")
    wrapped = f'import base64\nexec(base64.b64decode("{payload}").decode("utf-8"))\n'
    notes: list[str] = []

    out = unwrap_iter(wrapped, notes)

    assert out == original
    assert any("L1" in n for n in notes)


# ---------------------------------------------------------------------------
# L5: lambda wall unwrap recovers the inner expression
# ---------------------------------------------------------------------------

def test_unwrap_l5_lambda_wall_strips_one_layer() -> None:
    """One call to unwrap_once strips the (lambda: (lambda: X)())() wall.

    The L5_RE regex matches the outermost two-layer wrapper and captures
    the inner expression.  After one call, the inner literal is exposed
    and no lambda keyword remains (the 2-layer wall is reduced in a
    single subn() call).  We verify the literal is visible and an L5
    note was recorded.
    """
    text = 'result = (lambda: (lambda: "unwrapped_value")())()\n'
    notes: list[str] = []

    out = unwrap_once(text, notes)

    assert out is not None
    assert '"unwrapped_value"' in out
    assert any("L5" in n for n in notes)
    # The two-layer wrapper is fully gone; no lambda remains
    assert out.count("lambda") == 0


def test_unwrap_l5_lambda_wall_strips_nested_layers() -> None:
    """unwrap_iter peels the (lambda: (lambda: X)())() wall down to the bare literal.

    A 2-layer wall requires one unwrap_iter call (which itself loops
    until stable).  We check that the final text contains the literal
    and that at least one L5 note was recorded.
    """
    text = 'result = (lambda: (lambda: "deep")())()\n'
    notes: list[str] = []

    out = unwrap_iter(text, notes)

    assert out is not None
    assert '"deep"' in out
    # After peeling, no lambda remains (the inner literal is exposed)
    assert "(lambda" not in out
    lambda_notes = [n for n in notes if "L5" in n]
    assert len(lambda_notes) >= 1


# ---------------------------------------------------------------------------
# L2 and L3: marker round-trip (the unwrap stage emits a marker; we can
# parse the marker back into a code object)
# ---------------------------------------------------------------------------

def test_unwrap_l2_emits_sigil_marker(l2_marshal_py: pathlib.Path) -> None:
    """Unwrapping an L2 marshal layer emits a # __SigilCodeObjectMarker__ line.

    We then parse the marker back into a real code object and check that
    executing it recovers the original source's behaviour.
    """
    notes: list[str] = []
    text = l2_marshal_py.read_text(encoding="utf-8")
    out = unwrap_once(text, notes)
    assert out is not None
    assert "__SigilCodeObjectMarker__" in out
    assert any("L2" in n for n in notes)
    # The marker line embeds a real code object
    code = code_object_from_marker(out)
    # Executing the code object should not raise
    ns: dict = {}
    exec(code, ns)
    # The original source defined a `main` function; we can call it
    assert callable(ns.get("main"))


def test_unwrap_l3_emits_sigil_marker(l3_zlib_marshal_py: pathlib.Path) -> None:
    """Unwrapping an L3 zlib+marshal layer emits a marker line that is parseable."""
    notes: list[str] = []
    text = l3_zlib_marshal_py.read_text(encoding="utf-8")
    out = unwrap_once(text, notes)
    assert out is not None
    assert "__SigilCodeObjectMarker__" in out
    assert any("L3" in n for n in notes)
    # The marker line embeds a real (zlib+marshal) code object
    code = code_object_from_marker(out)
    ns: dict = {}
    exec(code, ns)
    assert callable(ns.get("main"))


# ---------------------------------------------------------------------------
# code_object_from_marker: feed a marker line directly
# ---------------------------------------------------------------------------

def test_code_object_from_marker_l2(l2_marshal_marker: pathlib.Path) -> None:
    """code_object_from_marker parses an L2 marker line into a real code object."""
    text = l2_marshal_marker.read_text(encoding="utf-8")
    code = code_object_from_marker(text)
    ns: dict = {}
    exec(code, ns)
    assert callable(ns.get("main"))


def test_code_object_from_marker_l3(l3_zlib_marshal_marker: pathlib.Path) -> None:
    """code_object_from_marker parses an L3 marker line into a real code object."""
    text = l3_zlib_marshal_marker.read_text(encoding="utf-8")
    code = code_object_from_marker(text)
    ns: dict = {}
    exec(code, ns)
    assert callable(ns.get("main"))


# ---------------------------------------------------------------------------
# Negative cases: no layer matches
# ---------------------------------------------------------------------------

def test_unwrap_returns_none_for_clean_source(hello_py: pathlib.Path) -> None:
    """A clean .py file with no obfuscation layers returns None from unwrap_once."""
    text = hello_py.read_text(encoding="utf-8")
    notes: list[str] = []
    out = unwrap_once(text, notes)
    # 'print("hello world")' has no L1/L2/L3/L5 layer, so unwrap returns None
    # (the caller then knows to skip the UNWRAP stage)
    assert out is None
    assert notes == []


def test_unwrap_iter_idempotent_on_clean_source(hello_py: pathlib.Path) -> None:
    """unwrap_iter returns the input unchanged when no layers match."""
    text = hello_py.read_text(encoding="utf-8")
    notes: list[str] = []
    out = unwrap_iter(text, notes)
    assert out == text


# ---------------------------------------------------------------------------
# _code_object_marker + code_object_from_marker round-trip
# ---------------------------------------------------------------------------

def test_code_object_marker_roundtrip() -> None:
    """A code object embedded in a marker line can be recovered verbatim."""
    original_code = compile("x = 1 + 2", "<test>", "exec")
    raw = marshal.dumps(original_code)
    marker_text = unwrap_mod._code_object_marker(original_code, raw_marshal=raw)
    recovered = code_object_from_marker(marker_text)
    # Exec the recovered code in a fresh namespace and check the side effect
    ns: dict = {}
    exec(recovered, ns)
    assert ns["x"] == 3
