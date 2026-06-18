"""Stage 2: UNWRAP.

Iteratively peel the obfuscation layers off until the source is either:
    - valid Python source (an AST can be parsed), or
    - a real .pyc file that Stage 4 (DECOMPILE) can handle.

The layers we know how to reverse (the inverse of the v1 obfuscator):
    L1 base64        exec(base64.b64decode(<lit>).decode('utf-8'))
                     -> replace with the decoded source string

    L2 marshal       exec(marshal.loads(base64.b64decode(<lit>)))
    L3 zlib+marshal  exec(marshal.loads(zlib.decompress(base64.b64decode(<lit>))))
                     -> extract the code object, write as a .pyc with a
                        proper 16-byte header for Stage 4 to decompile

    L5 lambda wall   top-level `expr` statements wrapped in
                     (lambda: (lambda: expr)())()
                     -> strip the wrapper, keep the inner expression

L4 (variable rename) is intentionally not reversed here. Once names are
gone, the only way to recover them is to compare structure against known
patterns or run an LLM over the bytecode. Both are out of scope for the
v1 unwrap stage. See 03_FEATURE_FEASIBILITY.md for the v2 plan.

L6 (bytecode) is the input to Stage 4, not the output of unwrap, so we
also don't touch it here.

This module is stdlib-only.
"""
from __future__ import annotations

import base64
import importlib.util
import marshal
import re
import struct
import time
import zlib
from pathlib import Path
from typing import Optional

L1_RE = re.compile(
    r"^import\s+base64\s*\n"
    r"exec\(\s*base64\.b64decode\(\s*['\"]([A-Za-z0-9+/=]+)['\"]\s*\)\s*\.decode\(\s*['\"]utf-8['\"]\s*\)\s*\)\s*$",
    re.MULTILINE,
)

L2_RE = re.compile(
    r"^import\s+base64\s*,\s*marshal\s*\n"
    r"exec\(\s*marshal\.loads\(\s*base64\.b64decode\(\s*['\"]([A-Za-z0-9+/=]+)['\"]\s*\)\s*\)\s*\)\s*$",
    re.MULTILINE,
)

L3_RE = re.compile(
    r"^import\s+base64\s*,\s*marshal\s*,\s*zlib\s*\n"
    r"exec\(\s*marshal\.loads\(\s*zlib\.decompress\(\s*base64\.b64decode\(\s*['\"]([A-Za-z0-9+/=]+)['\"]\s*\)\s*\)\s*\)\s*\)\s*$",
    re.MULTILINE,
)

# L5 wrapper: (lambda: (lambda: <inner>)())()  with arbitrary whitespace.
# Use non-greedy + DOTALL so nested wrappers strip outermost-first.
L5_RE = re.compile(
    r"\(lambda\s*:\s*\(lambda\s*:\s*(?P<inner>.*?)\s*\)\s*\(\s*\)\s*\)\s*\(\s*\)",
    re.DOTALL,
)


def unwrap_once(text: str, notes: list) -> Optional[str]:
    """Peel exactly one layer. Return new text, or None if no layer matched."""
    # L1: full-text source recovery.
    m = L1_RE.search(text)
    if m:
        decoded = base64.b64decode(m.group(1)).decode("utf-8")
        notes.append(f"unwrapped L1 (base64); recovered {len(decoded)} chars of source")
        return decoded

    # L2: extract marshal payload, hand off as code object to Stage 4.
    # Pass the raw bytes through so 3.12 bytecodes are preserved
    # verbatim (3.14's marshal reinterprets them).
    m = L2_RE.search(text)
    if m:
        raw = base64.b64decode(m.group(1))
        code = marshal.loads(raw)
        notes.append("unwrapped L2 (marshal); produced code object, "
                     "needs DECOMPILE stage")
        return _code_object_marker(code, raw_marshal=raw)

    # L3: zlib + marshal.
    m = L3_RE.search(text)
    if m:
        compressed = base64.b64decode(m.group(1))
        raw = zlib.decompress(compressed)
        code = marshal.loads(raw)
        notes.append("unwrapped L3 (zlib+marshal); produced code object, "
                     "needs DECOMPILE stage")
        return _code_object_marker(code, raw_marshal=raw)

    # L5: lambda-wall strip.  Look for the (lambda: (lambda: ...)())() shape.
    if "(lambda" in text:
        new_text, n = L5_RE.subn(r"\g<inner>", text)
        if n > 0:
            notes.append(f"unwrapped L5 (lambda wall); stripped {n} wrapper(s)")
            return new_text

    return None


def _code_object_marker(code, raw_marshal: bytes = None) -> str:
    """A line that says 'code object follows' for the DECOMPILE stage.

    If ``raw_marshal`` is provided, we embed those exact bytes (so the
    original 3.12 bytecodes are preserved verbatim).  Otherwise we fall
    back to ``marshal.dumps(code)`` which under Python 3.14 will
    reinterpret 3.12 code objects and mangle the bytecodes.
    """
    if raw_marshal is not None:
        encoded = base64.b64encode(raw_marshal).decode("ascii")
    else:
        encoded = base64.b64encode(marshal.dumps(code)).decode("ascii")
    return f"# __SigilCodeObjectMarker__:{encoded}\n"


def unwrap_iter(text: str, notes: list, max_iterations: int = 16) -> str:
    """Peel layers until stable or marker emitted. See module docstring."""
    current = text
    for i in range(max_iterations):
        new = unwrap_once(current, notes)
        if new is None:
            notes.append(f"unwrap: stable after {i} iteration(s)")
            return current
        current = new
        if current.startswith("# __SigilCodeObjectMarker__:"):
            return current
    notes.append(f"unwrap: hit max_iterations={max_iterations}; stopping")
    return current


def unwrap_file(input_path: Path, out_dir: Path) -> tuple:
    """Read input_path, unwrap layers, write to out_dir/<name>.py.

    For .pyc inputs the unwrap stage is a no-op: the file is binary and
    gets handed to the DECOMPILE stage as-is.  The unwrap stage only
    makes sense for text wrappers (L1 base64, L2/L3 marshal, L5 lambda
    wall, L4 in the future).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    if input_path.suffix == ".pyc":
        # Pass through unchanged.  decompile stage reads the .pyc.
        out_path = out_dir / input_path.name
        out_path.write_bytes(input_path.read_bytes())
        return out_path, [f"unwrap: .pyc input is binary; passing through to DECOMPILE stage"], 0
    # newline='' preserves line endings exactly - no platform translation.
    # Without this, Windows would convert LF -> CRLF on write, which the
    # downstream Stage 4 (decompiler) might choke on.
    text = input_path.read_text(encoding="utf-8", errors="replace", newline="")
    notes: list = []
    result = unwrap_iter(text, notes)
    iterations = sum(1 for n in notes if n.startswith("unwrapped L"))

    out_path = out_dir / input_path.name
    with out_path.open("w", encoding="utf-8", newline="") as f:
        f.write(result)
    return out_path, notes, iterations


def code_object_from_marker(marker_text: str):
    """Given a marker string, return the code object or None."""
    if not marker_text.startswith("# __SigilCodeObjectMarker__:"):
        return None
    payload_b64 = marker_text.split(":", 1)[1].strip()
    return marshal.loads(base64.b64decode(payload_b64))


def write_pyc(code, dest: Path) -> Path:
    """Write a code object to a real CPython .pyc file."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    magic = importlib.util.MAGIC_NUMBER
    flags = 0
    timestamp = int(time.time())
    source_size = 0
    header = magic + struct.pack("<III", flags, timestamp, source_size)
    dest.write_bytes(header + marshal.dumps(code))
    return dest
