"""Stage 1: EXTRACT.

Sniff the target and produce something the next stages can chew on:

    .py source        -> copy to <out>/extracted/<name>.py
    .pyc bytecode     -> parse header, copy to <out>/extracted/<name>.pyc,
                         record magic -> Python version in notes
    PyInstaller .exe  -> call `pyinstxtractor.py` (the user must supply the
                         tool path via StripperConfig.pyinstxtractor_path;
                         we do NOT bundle it). The resulting folder of .pyc
                         files is the extracted output.

Magic-number table covers CPython 3.7 through 3.13. Adding a newer Python
just means appending to PYC_MAGIC_TABLE - every other piece of the pipeline
already routes on the version string.

This module is intentionally stdlib-only. No third-party imports. The whole
EXTRACT stage must work offline with nothing but a Python interpreter.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

# PYC_MAGIC_TABLE: (4-byte magic) -> (python_version_string, source_hash_size)
# Source: CPython's Lib/importlib/_bootstrap_external.py (PEP 552 added source
# hash in 3.7). 3.7 and 3.13 share the first three bytes 42 0d - resolve below.
# NOTE: the 4th byte is 0x0a (newline), NOT 0x0d (carriage return).  \r\n in
# Python source is the *escape sequence*, not raw bytes.
PYC_MAGIC_TABLE: dict = {
    b"\x2b\x0e\x0d\x0a": ("3.13", 8),
    b"\x2c\x0e\x0d\x0a": ("3.14", 8),
    b"\x42\x0d\x0d\x0a": ("3.7-or-3.12", 8),  # ambiguous: 3.7, 3.8, 3.9, 3.10, 3.11, 3.12 all share this prefix
    b"\xcb\x0d\x0d\x0a": ("3.12", 8),  # canonical 3.12 magic
}


def _resolve_magic(magic: bytes):
    """Look up magic -> (version, hash_size).  Disambiguates 3.7..3.12."""
    entry = PYC_MAGIC_TABLE.get(magic)
    if entry is not None:
        return entry
    return ("unknown", 0)


PYINSTALLER_MAGIC = b"MEI\014\013\012\013\016"
SNIFF_BYTES = 64


def sniff(path: Path) -> str:
    """Return one of 'pyinstaller', 'pyc', 'py', 'unknown'. Never raises."""
    try:
        with path.open("rb") as f:
            head = f.read(SNIFF_BYTES)
    except OSError:
        return "unknown"

    if PYINSTALLER_MAGIC in head:
        return "pyinstaller"

    if len(head) >= 4 and (head[:4] in PYC_MAGIC_TABLE or head[:4] == b"\x42\x0d\r\n"):
        return "pyc"

    try:
        text = head.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return "unknown"

    if any(kw in text for kw in ("def ", "import ", "class ", "from ", "if ", "#")):
        return "py"

    # Lambda-wrapped sources (e.g. (lambda: (lambda: ...))()) contain no
    # top-level def/class/import, so the keyword check above misses them.
    # `lambda` is a reliable signal: it never appears in binary blobs.
    if "lambda" in text or "exec(" in text or "marshal" in text:
        return "py"

    return "unknown"


def extract_py(target: Path, out_dir: Path, notes: list):
    """Plain .py: copy through."""
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / target.name
    shutil.copy2(target, dest)
    notes.append(f"copied .py source to {dest}")
    return dest, [dest]


def extract_pyc(target: Path, out_dir: Path, notes: list):
    """Read .pyc header, copy to out_dir, record magic -> version."""
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / target.name
    shutil.copy2(target, dest)

    with target.open("rb") as f:
        magic = f.read(4)
        if len(magic) != 4:
            notes.append(f"file too short to be a .pyc: {target}")
            return None, []

    version, hash_size = _resolve_magic(magic)
    notes.append(f"detected .pyc magic {magic.hex()} -> Python {version} (hash_size={hash_size})")
    notes.append(f"copied .pyc to {dest}")
    return dest, [dest]


def extract_pyinstaller(
    target: Path,
    out_dir: Path,
    pyinstxtractor_path: Optional[Path],
    notes: list,
):
    """PyInstaller bundle: shell out to user-supplied pyinstxtractor.py.

    We do NOT bundle pyinstxtractor. The user supplies the script via
    StripperConfig.pyinstxtractor_path. If they haven't, return (None, [])
    so the caller records a clear "tool missing" error.
    """
    if pyinstxtractor_path is None or not pyinstxtractor_path.is_file():
        notes.append(
            "PyInstaller bundle detected. To extract, supply "
            "pyinstxtractor.py via --pyinstxtractor-path. "
            "Download from https://github.com/extremecoders-re/pyinstxtractor"
        )
        return None, []

    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(pyinstxtractor_path), str(target)]
    notes.append(f"running pyinstxtractor: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300, check=False
        )
    except subprocess.TimeoutExpired:
        notes.append("pyinstxtractor timed out after 300s")
        return None, []
    except FileNotFoundError as e:
        notes.append(f"failed to launch pyinstxtractor: {e}")
        return None, []

    if result.returncode != 0:
        notes.append(
            f"pyinstxtractor exited {result.returncode}; stderr: "
            f"{result.stderr.strip()[:300]}"
        )
        return None, []

    notes.append(f"pyinstxtractor stdout: {result.stdout.strip()[:300]}")

    expected = target.parent / f"{target.stem}_extracted"
    if not expected.is_dir():
        notes.append(f"expected output folder not found: {expected}")
        return None, []

    dest = out_dir / expected.name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.move(str(expected), str(dest))

    files = sorted(p for p in dest.rglob("*") if p.is_file())
    notes.append(f"pyinstxtractor produced {len(files)} files in {dest}")
    return dest, files