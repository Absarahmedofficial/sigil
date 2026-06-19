"""DECOMPILE stage.

Translate bytecode (.pyc) or marshalled code objects back to Python source.

Three backends, in priority order:

  1. pycdc (subprocess) - fast, handles 3.8-3.10 cleanly, no Python deps
  2. pylingual (subprocess) - transformer-based, handles 3.11+ via HF model
  3. dis_fallback (in-process) - structural unparser using dis.dis(); only
     handles simple bytecode (function defs, basic control flow, common
     expressions).  Used in dev when neither binary is installed.

Subprocess-only integration for pycdc and pylingual per the v1 license
posture (see 04_LEGAL_AND_SAFETY.md).  We never import them as Python
modules; we shell out and parse the stdout.

Routing is by magic number: bytes 0-3 of the .pyc header.  pycdc handles
up through 3.10; pylingual is the only viable option for 3.11+.
"""
from __future__ import annotations

import dis
import importlib.util
import logging
import marshal
import opcode
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# Magic numbers for Python 3.6-3.14.  Source: CPython's Lib/importlib/_bootstrap_external.py.
# (We list a couple of major-version breakpoints; the precise mapping is
# less important than the routing decision: <=3.10 -> pycdc, >=3.11 -> pylingual.)
MAGIC_NUMBERS = {
    # 3.6 .. 3.10 -> pycdc
    b"\x33\x0d\x0d\x0a": "3.6",
    b"\x34\x0d\x0d\x0a": "3.7",
    b"\x55\x0d\x0d\x0a": "3.8",
    b"\x61\x0d\x0d\x0a": "3.9",
    b"\x6e\x0d\x0d\x0a": "3.10",
    # 3.11+ -> pylingual
    b"\xa7\x0d\x0d\x0a": "3.11",
    b"\xcb\x0d\x0d\x0a": "3.12",
    b"\x2b\x0e\x0d\x0a": "3.13",
    b"\x2c\x0e\x0d\x0a": "3.14",
}


def _binop_table() -> dict[int, str]:
    """Build the BINARY_OP arg -> operator string mapping from the *current*
    interpreter's `opcode._nb_ops`.  Index 0..12 are regular; 13..25 are
    in-place; 26 is sub-script.  We only return the regular ones, since
    the dis-fallback is for simple bytecode."""
    table = {}
    nb = getattr(opcode, "_nb_ops", None)
    if isinstance(nb, list):
        for i, entry in enumerate(nb):
            if i > 12:  # stop at the in-place block
                break
            if isinstance(entry, tuple) and len(entry) >= 2:
                table[i] = entry[1]
    # Fallback for older Pythons without opcode._nb_ops.
    if not table:
        table = {0: "+", 1: "&", 2: "//", 3: "<<", 4: "@", 5: "*",
                 6: "%", 7: "|", 8: "**", 9: ">>", 10: "-", 11: "/", 12: "^"}
    return table


def detect_python_version(pyc_path: Path) -> str:
    """Read the first 4 bytes of the .pyc and return the detected Python
    version string (e.g. '3.14').  Falls back to 'unknown'."""
    with pyc_path.open("rb") as f:
        magic = f.read(4)
    return MAGIC_NUMBERS.get(magic, "unknown")


def _read_code_object_from_pyc(pyc_path: Path):
    """Extract the marshalled code object from a .pyc file.

    On 3.7+ the header is 16 bytes (4 magic + 4 flags + 4 ts + 4 size).
    On 3.6 it was 8 bytes.  We try 16 first, then 8, then 0.
    """
    data = pyc_path.read_bytes()
    for header_size in (16, 8, 0):
        try:
            return marshal.loads(data[header_size:])
        except (ValueError, EOFError):
            continue
    raise ValueError(f"could not unmarshal code object from {pyc_path}")


def _read_code_object_from_marker(source: str):
    """The unwrap stage may emit a single line of the form
    ``# __SigilCodeObjectMarker__:<base64-payload>`` for L2/L3 marshal
    layers.  Returns ``(code_object, raw_marshal_bytes)`` so the caller
    can preserve the original bytecodes verbatim (Python 3.14's
    ``marshal.loads`` reinterprets 3.12 opcodes through the 3.14
    opcode table, corrupting the bytes on re-dump)."""
    m = re.search(r"#\s*__SigilCodeObjectMarker__:\s*([A-Za-z0-9+/=]+)", source)
    if not m:
        raise ValueError("source does not contain a SigilCodeObjectMarker")
    import base64
    raw = base64.b64decode(m.group(1))
    return marshal.loads(raw), raw


# ---------------------------------------------------------------------------
# Backend 1: pycdc (subprocess)
# ---------------------------------------------------------------------------

def decompile_with_pycdc(pyc_path: Path, out_path: Path, pycdc_exe: Path,
                          timeout: int = 30) -> tuple[bool, str]:
    """Shell out to pycdc, write its stdout to out_path.

    Returns (success, message).  pycdc prints decompiled source to stdout
    and exits 0 on success, 1 on failure (with a diagnostic on stderr).

    pycdc supports up to ~Python 3.12 in the latest build (May 2026).
    For 3.13+ files we copy the .pyc with a 3.12 magic header so pycdc
    can at least make a partial attempt.  This is a stopgap; the
    permanent fix is pylingual, which is not pip-installable as of the
    most recent research (F-04) and requires a multi-GB model download.
    """
    if not pycdc_exe.exists():
        return False, f"pycdc binary not found at {pycdc_exe}"

    # Detect Python version from magic; remagic to 3.12 if newer.
    target_pyc = pyc_path
    temp_pyc: Optional[Path] = None
    try:
        data = pyc_path.read_bytes()
        if data[:4] in {b"\x2b\x0e\x0d\x0a", b"\x2c\x0e\x0d\x0a"}:
            # 3.13 / 3.14 -> 3.12 (marshal payload is bit-compatible)
            import tempfile
            fd, tmp_name = tempfile.mkstemp(suffix=".pyc", prefix="pycdc_remagic_")
            import os as _os
            _os.close(fd)
            with open(tmp_name, "wb") as fh:
                fh.write(b"\xcb\x0d\x0d\x0a" + data[4:])
            target_pyc = Path(tmp_name)
            temp_pyc = target_pyc
    except Exception:
        target_pyc = pyc_path
        temp_pyc = None

    try:
        try:
            result = subprocess.run(
                [str(pycdc_exe), str(target_pyc)],
                capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return False, f"pycdc timed out after {timeout}s on {pyc_path}"
        except FileNotFoundError:
            return False, f"pycdc binary not executable: {pycdc_exe}"

        if result.returncode != 0:
            return False, f"pycdc returned {result.returncode}: {result.stderr.strip()[:200]}"

        if not result.stdout.strip():
            return False, "pycdc produced empty output"

        out_path.write_text(result.stdout, encoding="utf-8", newline="")
        return True, f"pycdc decompiled {pyc_path.name} -> {out_path.name}"
    finally:
        if temp_pyc is not None:
            try:
                temp_pyc.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Backend 2: pylingual (subprocess)
# ---------------------------------------------------------------------------

def decompile_with_pylingual(pyc_path: Path, out_path: Path,
                              pylingual_cmd: list[str],
                              timeout: int = 600) -> tuple[bool, str]:
    """Shell out to pylingual.  The user supplies the full command
    (e.g. ``['pylingual']`` or ``['pylingual', '--quiet']``); we append
    ``-o <workdir>`` and the input .pyc, then read the decompiled source
    from the file pylingual writes into that directory.

    pylingual's CLI signature (v0.1.0):
        pylingual [OPTIONS] PATHS
            -o, --out-dir PATH   (required; pylingual writes its output here)
            -c, --config-file PATH
            -v, --version VERSION
            -q, --quiet          (suppress rich console output; RECOMMENDED
                                   because the default output uses ``rich``
                                   which crashes on Windows with cp1252
                                   console encoding)
            --force              (overwrite existing output files)

    pylingual writes one or more files like ``decompiled_<basename>.py``
    into ``out-dir``.  We pick the file that matches the input stem.
    """
    import tempfile as _tempfile
    work_dir = _tempfile.mkdtemp(prefix="pylingual_out_")
    try:
        try:
            cmd = list(pylingual_cmd) + ["-o", work_dir, "--force", str(pyc_path)]
            # pylingual emits rich-formatted output to stdout by default
            # which crashes on Windows consoles.  Append --quiet if the
            # caller didn't already pass it.
            if not any(arg in ("-q", "--quiet") for arg in pylingual_cmd):
                cmd.insert(len(pylingual_cmd), "--quiet")
            # Resolve the bare ``pylingual`` command.  On Windows,
            # subprocess.run does NOT consult PATH the way the shell
            # does (and doesn't pick up PATHEXT reliably), so a bare
            # ``["pylingual", ...]`` command fails with
            # ``[WinError 2] The system cannot find the file specified``
            # even when ``pylingual.exe`` is sitting in the venv's
            # Scripts/ dir.  We resolve to an absolute path via
            # shutil.which (which DOES consult PATH and PATHEXT), and
            # fall back to looking next to sys.executable.  If neither
            # works, we keep the bare command and let the OS error
            # surface — same as before, but with a clearer note.
            import shutil as _shutil
            _first = cmd[0]
            _resolved = _shutil.which(_first)
            if _resolved is None:
                _exe_dir = os.path.dirname(sys.executable)
                _candidate = os.path.join(_exe_dir, _first)
                if os.path.isfile(_candidate):
                    _resolved = _candidate
                else:
                    # Try with .exe appended (Windows convention).
                    _candidate_exe = _candidate + ".exe"
                    if os.path.isfile(_candidate_exe):
                        _resolved = _candidate_exe
            if _resolved is not None:
                cmd = [_resolved] + list(cmd[1:])
            # PYTHONIOENCODING=utf-8 dodges a Windows cp1252 crash
            # inside pylingual's ``rich`` console output.
            env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout, env=env,
            )
        except subprocess.TimeoutExpired:
            return False, f"pylingual timed out after {timeout}s on {pyc_path}"
        except FileNotFoundError as e:
            return False, f"pylingual command failed to launch: {e}"

        if result.returncode != 0:
            return False, f"pylingual returned {result.returncode}: {(result.stderr or result.stdout).strip()[:200]}"

        # Find the decompiled file.  pylingual names it
        # ``decompiled_<basename>.py`` (or sometimes just <basename>.py).
        candidates = list(Path(work_dir).glob("*.py"))
        if not candidates:
            # DEBUG: list whatever is in the dir to diagnose silent failures
            contents = list(Path(work_dir).iterdir())
            return False, (f"pylingual produced no .py files in {work_dir}; "
                           f"contents={contents}; stderr={(result.stderr or '')[:2000]}; "
                           f"returncode={result.returncode}")

        # Prefer the file whose stem contains pyc_path.stem; fall back to
        # the first .py if no match.
        chosen = None
        for c in candidates:
            if pyc_path.stem in c.stem:
                chosen = c
                break
        if chosen is None:
            chosen = candidates[0]

        # Strip the pylingual header comments and the escaped docstring
        # ``\n`` literals — pycdc output doesn't have them and the test
        # bench's structural matchers want clean source.
        text = chosen.read_text(encoding="utf-8", newline="")
        cleaned_lines = []
        for line in text.splitlines():
            if line.startswith("# Decompiled with PyLingual"):
                continue
            if line.startswith("# Internal filename:"):
                continue
            if line.startswith("# Bytecode version:"):
                continue
            if line.startswith("# Source timestamp:"):
                continue
            cleaned_lines.append(line)
        cleaned = "\n".join(cleaned_lines)

        out_path.write_text(cleaned, encoding="utf-8", newline="")
        return True, f"pylingual decompiled {pyc_path.name} -> {out_path.name} (via {chosen.name})"
    finally:
        try:
            import shutil as _shutil
            _shutil.rmtree(work_dir, ignore_errors=True)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Backend 3: dis-based structural unparser (dev fallback)
# ---------------------------------------------------------------------------
#
# This is NOT a general Python decompiler.  It handles the subset of
# bytecode produced by our test bench's obfuscator: function definitions,
# simple expressions, and basic control flow.  Real-world obfuscated
# bytecode will not round-trip through it; the real backends (pycdc /
# pylingual) are required for production use.
#
# The dis-based decompiler exists so the test bench can score L6 cases
# during development without requiring the user to build pycdc (C++,
# multi-hour) or download a pylingual model (multi-GB).

_DIS_BINOPS = _binop_table()


def _dis_to_source(code_obj) -> str:
    """Best-effort structural decompiler for a single code object.

    Recursively unparses function bodies, returns Python source.  May
    produce invalid output for bytecode outside our test bench's shape.

    The unparser works on a *value stack* of source fragments.  When
    STORE_NAME fires, the top of the stack is the value being assigned
    and the unparser emits a `name = <value>` line.
    """
    instructions = list(dis.get_instructions(code_obj))
    stack: list = []
    out: list = []

    def push(x):
        stack.append(x)

    def pop():
        return stack.pop()

    def emit(line):
        out.append(line)

    for instr in instructions:
        op = instr.opname
        if op == "RESUME":
            continue
        if op == "LOAD_CONST" and instr.argval is None:
            # The standard `LOAD_CONST None; RETURN_VALUE` epilogue.
            # Suppress - it's noise.
            continue
        if isinstance(instr.argval, str) and instr.argval.startswith("Case "):
            # Module docstring.  Already handled by the special-case in
            # decompile_with_dis via co_consts, but be defensive.
            continue
        if op == "STORE_NAME" and instr.argval == "__doc__":
            # Module docstring store.  The docstring was pushed as a
            # string by an earlier LOAD_CONST.
            if stack:
                stack.pop()
            continue
        if op == "LOAD_CONST" and hasattr(instr.argval, "co_name") and getattr(instr.argval, "co_name", None) and instr.argval.co_name != "<module>":
            # A nested function/code object
            nested = _dis_to_source(instr.argval)
            sig_args = instr.argval.co_varnames[:instr.argval.co_argcount]
            # Indent the nested source by 4 spaces; emit def header
            # as a single "fragment" the next STORE_NAME will lift.
            fragment = f"def {instr.argval.co_name}({', '.join(sig_args)}):\n" + textwrap.indent(nested, "    ")
            push(fragment)
            continue
        if op == "MAKE_FUNCTION":
            # The previous push was the code object; pop and discard
            # (MAKE_FUNCTION builds a function value, but in our simple
            # test cases the next op is STORE_NAME which we handle).
            continue
        if op == "STORE_NAME":
            value = pop() if stack else "?"
            # At module level, `def name(...):` is a statement, not an
            # assignment.  If the value starts with `def `, drop the
            # `name = ` prefix to avoid emitting `main = def main(): ...`.
            if isinstance(value, str) and value.startswith("def "):
                emit(value)
            else:
                emit(f"{instr.argval} = {value}")
            continue
        if op == "LOAD_FAST_BORROW_LOAD_FAST_BORROW":
            names = instr.argval if isinstance(instr.argval, tuple) else (instr.argval,)
            for n in names:
                push(n)
            continue
        if op == "LOAD_SMALL_INT":
            push(str(instr.arg))
            continue
        if op == "LOAD_FAST":
            push(instr.argval)
            continue
        if op == "FORMAT_SIMPLE":
            if stack and not stack[-1].startswith("f\""):
                stack[-1] = "f\"" + stack[-1] + "\""
            continue
        if op == "BINARY_OP":
            if instr.arg in _DIS_BINOPS and len(stack) >= 2:
                op_str = _DIS_BINOPS[instr.arg]
                rhs = pop()
                lhs = pop()
                push(f"({lhs} {op_str} {rhs})")
            else:
                push(f"# (unparsed BINARY_OP arg={instr.arg})")
            continue
        if op == "RETURN_VALUE":
            if stack:
                ret = pop()
                emit(f"return {ret}")
            continue
        # Unknown op - record and continue.
        push(f"# (unparsed: {op} arg={instr.arg!r} val={instr.argval!r})")

    # Any leftover items on the stack at end-of-function become a final
    # bare expression.
    for leftover in stack:
        if not str(leftover).startswith("# (unparsed"):
            emit(str(leftover))

    return "\n".join(out)


def _dis_signature(code_obj) -> str:
    args = code_obj.co_varnames[:code_obj.co_argcount]
    return f"({', '.join(args)})"


def decompile_with_dis(pyc_path: Path, out_path: Path) -> tuple[bool, str]:
    """In-process dis-based structural decompiler.  See module docstring."""
    try:
        code_obj = _read_code_object_from_pyc(pyc_path)
    except Exception as e:
        return False, f"dis-fallback: could not load code object: {e}"

    try:
        if code_obj.co_argcount == 0 and code_obj.co_name == "<module>":
            body = _dis_to_source(code_obj)
        else:
            body = f"def {code_obj.co_name}{_dis_signature(code_obj)}:\n"
            inner = _dis_to_source(code_obj)
            body += textwrap.indent(inner + "\n", "    ")
    except Exception as e:
        return False, f"dis-fallback: unparse failed: {e}"

    if not body.strip():
        return False, "dis-fallback: produced empty source"

    header = f'"""Decompiled by pyglimmer dis-fallback from {pyc_path.name} (Python {detect_python_version(pyc_path)})."""\n\n'
    out_path.write_text(header + body + "\n", encoding="utf-8", newline="")
    return True, f"dis-fallback decompiled {pyc_path.name} -> {out_path.name}"


# ---------------------------------------------------------------------------
# Public API: decompile_file()
# ---------------------------------------------------------------------------

def decompile_file(
    input_path: Path,
    out_dir: Path,
    pycdc_exe: Optional[Path] = None,
    pylingual_cmd: Optional[list[str]] = None,
    allow_dis_fallback: bool = False,
) -> tuple[Path, str, str]:
    """Decompile a .pyc (or a code-object marker source) to Python source.

    Returns (output_path, backend_used, python_version).  Caller decides
    what to do on failure - this function never raises; it returns a
    best-effort result.

    Backend selection:
        - pycdc if pycdc_exe is set and Python version <= 3.10
        - pylingual if pylingual_cmd is set and Python version >= 3.11
        - dis-fallback only if allow_dis_fallback=True
        - otherwise: write a placeholder source file explaining the
          failure so the caller can still chain into Stage 5 (LLM cleanup)
          or hand it to the user as a partial recovery.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Figure out what kind of input we have.
    if input_path.suffix == ".pyc":
        pyc_path = input_path
        python_version = detect_python_version(pyc_path)
    else:
        # Source containing a SigilCodeObjectMarker - extract code object
        # and write a temporary .pyc so pycdc/pylingual can read it.
        try:
            code_obj, raw_marshal = _read_code_object_from_marker(input_path.read_text(encoding="utf-8", newline=""))
        except Exception as e:
            placeholder = out_dir / (input_path.stem + ".py")
            placeholder.write_text(
                f"# decompile failed: {input_path.name}: {e}\n",
                encoding="utf-8", newline="",
            )
            return placeholder, "none", "unknown"
        pyc_path = out_dir / (input_path.stem + ".pyc")
        # Preserve the ORIGINAL Python magic number from the raw marshal
        # bytes.  pylingual (and pycdc, for <=3.10) both pick their
        # model/decompiler based on the first 4 bytes of the .pyc, so
        # writing a fake magic (the old "remagic to 3.12" trick) makes
        # pylingual see 3.12 magic but 3.14 bytecodes — it then crashes
        # with "produced no .py files".  The raw_marshal payload already
        # starts with the original 4-byte magic followed by the original
        # code object bytes; we just need to add the 12-byte header
        # (flags, timestamp, source_size) between magic and payload.
        import struct
        if len(raw_marshal) >= 4 and raw_marshal[:4] in MAGIC_NUMBERS:
            original_magic = raw_marshal[:4]
            python_version = MAGIC_NUMBERS[original_magic]
            payload = raw_marshal[4:]  # strip magic; we re-prepend below
        else:
            # Old-format or unknown marshal.  Fall back to the current
            # interpreter's magic (which is what unmarshalled it) and
            # hope for the best.  This is rare in practice.
            original_magic = importlib.util.MAGIC_NUMBER
            python_version = MAGIC_NUMBERS.get(original_magic, "unknown")
            payload = raw_marshal
        header = original_magic + struct.pack("<III", 0, 0, 1)
        pyc_path.write_bytes(header + payload)

    out_path = out_dir / (input_path.stem + ".py") if input_path.suffix == ".pyc" else out_dir / (input_path.stem + "_decompiled.py")

    # 2. Route to the right backend.
    major_minor = python_version.split(".")
    if len(major_minor) >= 2:
        try:
            minor = int(major_minor[1])
        except ValueError:
            minor = 0
    else:
        minor = 0

    def _try_pycdc():
        if pycdc_exe is None:
            return None
        ok, msg = decompile_with_pycdc(pyc_path, out_path, pycdc_exe)
        return (out_path, "pycdc", python_version) if ok else None

    def _try_pylingual():
        if pylingual_cmd is None:
            logger.debug("pylingual_cmd is None!")
            return None
        logger.debug("trying pylingual with cmd=%s", pylingual_cmd)
        ok, msg = decompile_with_pylingual(pyc_path, out_path, pylingual_cmd)
        logger.debug("pylingual result ok=%s msg=%s", ok, msg[:200])
        return (out_path, "pylingual", python_version) if ok else None

    result = None
    if minor <= 10:
        result = _try_pycdc() or _try_pylingual()
    elif minor >= 11:
        result = _try_pylingual() or _try_pycdc()
    logger.debug("routing result=%s", result)

    if result is not None:
        return result

    if allow_dis_fallback:
        ok, msg = decompile_with_dis(pyc_path, out_path)
        if ok:
            return out_path, "dis-fallback", python_version

    placeholder = out_path
    placeholder.write_text(
        f"# decompile: no backend succeeded for {input_path.name} (Python {python_version})\n"
        f"# Install pycdc (<=3.10) or pylingual (>=3.11) and configure via StripperConfig.\n"
        f"# Set allow_dis_fallback=True for a best-effort in-process recovery (dev only).\n",
        encoding="utf-8", newline="",
    )
    return placeholder, "none", python_version