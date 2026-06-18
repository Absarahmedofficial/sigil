"""Shared pytest fixtures for the pyglimmer_toolkit test suite.

These fixtures create real files in a temporary directory so tests
exercise the actual file I/O paths through extract/unwrap/decompile.
We never mock the file system for tests that touch paths.

The fixtures here are intentionally small and deterministic.  Larger
fixtures (e.g. obfuscated test cases) live in eval/cases/ and are
referenced by tests/eval/ rather than imported here.
"""
from __future__ import annotations

import base64
import marshal
import pathlib
import textwrap
import zlib

import pytest


# ---------------------------------------------------------------------------
# Temporary directories
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_workdir(tmp_path: pathlib.Path) -> pathlib.Path:
    """An isolated working directory for the duration of one test."""
    work = tmp_path / "work"
    work.mkdir()
    return work


# ---------------------------------------------------------------------------
# Plain Python source fixtures
# ---------------------------------------------------------------------------

HELLO_WORLD_SOURCE = 'def main():\n    return "hello world"\n'


@pytest.fixture
def hello_py(tmp_workdir: pathlib.Path) -> pathlib.Path:
    """A trivial .py file with a single function definition.

    Uses `def main` so that sniff() classifies it as 'py' (sniff looks for
    one of: def, import, class, from, if, #) and so the stripper's
    extract stage treats it as a real Python source.
    """
    p = tmp_workdir / "hello.py"
    p.write_text(HELLO_WORLD_SOURCE, encoding="utf-8")
    return p


@pytest.fixture
def arithmetic_py(tmp_workdir: pathlib.Path) -> pathlib.Path:
    """A .py file with a function (matches eval/cases/01_arithmetic.py)."""
    p = tmp_workdir / "01_arithmetic.py"
    p.write_text(textwrap.dedent('''\
        """Case 01: basic arithmetic.

        main(a, b) -> a + b * 2 - 1, formatted as a string.
        """
        def main(a, b):
            return f"{a + b * 2 - 1}"
    '''), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# L1 (base64) fixture: source wrapped in a one-shot base64 decode
# ---------------------------------------------------------------------------

@pytest.fixture
def l1_base64_py(tmp_workdir: pathlib.Path) -> pathlib.Path:
    """A .py file whose body is a one-shot base64-wrapped hello script.

    The L1 regex (in pyglimmer_toolkit/core/unwrap.py) requires
    `import base64` at the start of a line followed by
    `exec(base64.b64decode("...").decode("utf-8"))` on the next line.
    No leading comment is allowed because the regex is anchored with ^
    and uses re.MULTILINE.  The format matches what eval/obfuscate.py
    produces for L1 fixtures.
    """
    payload = base64.b64encode(HELLO_WORLD_SOURCE.encode("utf-8")).decode("ascii")
    p = tmp_workdir / "l1_base64.py"
    p.write_text(
        f'import base64\nexec(base64.b64decode("{payload}").decode("utf-8"))\n',
        encoding="utf-8",
    )
    return p


# ---------------------------------------------------------------------------
# L5 (lambda wall) fixture: matches the eval/obfuscated L5 patterns
# ---------------------------------------------------------------------------

@pytest.fixture
def l5_lambda_wall_py(tmp_workdir: pathlib.Path) -> pathlib.Path:
    """A .py file whose body is a lambda wall (no top-level def/import).

    The L5_RE regex strips one layer of the (lambda: (lambda: X)())()
    wrapper per call.  unwrap_iter() calls unwrap_once() repeatedly
    until stable.  We use a 2-layer wall so a single unwrap_iter pass
    peels both layers and recovers the literal.
    """
    p = tmp_workdir / "l5_lambda_wall.py"
    p.write_text('result = (lambda: (lambda: "unwrapped_value")())()\n',
                 encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# L2 (marshal) fixture: code object serialised in an `import base64, marshal;
# exec(marshal.loads(base64.b64decode(...)))` wrapper
# ---------------------------------------------------------------------------

def _marshal_wrapper_source(source: str) -> str:
    """Build a .py file that wraps `source` in an L2 marshal layer.

    The L2_RE regex in pyglimmer_toolkit/core/unwrap.py requires:
        line 1: `import base64 , marshal`
        line 2: `exec(marshal.loads(base64.b64decode("<b64>")))`
    """
    code = compile(source, "<test>", "exec")
    raw = marshal.dumps(code)
    b64 = base64.b64encode(raw).decode("ascii")
    return f'import base64, marshal\nexec(marshal.loads(base64.b64decode("{b64}")))\n'


def _marshal_marker_text(source: str) -> str:
    """Build a SigilCodeObjectMarker line that embeds the code object.

    This is what the UNWRAP stage produces *after* detecting an L2
    marshal layer.  Use the l2_marshal_marker fixture for tests that
    need to feed the marker back into code_object_from_marker.
    """
    code = compile(source, "<test>", "exec")
    raw = marshal.dumps(code)
    b64 = base64.b64encode(raw).decode("ascii")
    return f'# __SigilCodeObjectMarker__:{b64}\n'


@pytest.fixture
def l2_marshal_py(tmp_workdir: pathlib.Path, arithmetic_py: pathlib.Path) -> pathlib.Path:
    """An L2-wrapped .py file (input to the unwrap stage)."""
    p = tmp_workdir / "l2_marshal.py"
    p.write_text(_marshal_wrapper_source(arithmetic_py.read_text(encoding="utf-8")),
                 encoding="utf-8")
    return p


@pytest.fixture
def l2_marshal_marker(tmp_workdir: pathlib.Path, arithmetic_py: pathlib.Path) -> pathlib.Path:
    """A .py file whose body is a SigilCodeObjectMarker line (output of unwrap stage)."""
    p = tmp_workdir / "l2_marshal_marker.py"
    p.write_text(_marshal_marker_text(arithmetic_py.read_text(encoding="utf-8")),
                 encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# L3 (zlib+marshal) fixture: same as L2 but the code object is zlib-compressed
# ---------------------------------------------------------------------------

def _zlib_marshal_wrapper_source(source: str) -> str:
    """Build a .py file that wraps `source` in an L3 zlib+marshal layer."""
    code = compile(source, "<test>", "exec")
    raw = marshal.dumps(code)
    compressed = zlib.compress(raw, wbits=15)
    b64 = base64.b64encode(compressed).decode("ascii")
    return f'import base64, marshal, zlib\nexec(marshal.loads(zlib.decompress(base64.b64decode("{b64}"))))\n'


def _zlib_marshal_marker_text(source: str) -> str:
    """A SigilCodeObjectMarker line for an L3 zlib+marshal payload.

    The marker embeds the *decompressed* marshal bytes (raw_marshal),
    not the zlib-compressed bytes.  This matches what the UNWRAP stage
    produces after detecting the L3 wrapper: it decompresses first, then
    writes the raw marshal bytes into the marker so the DECOMPILE stage
    can feed them straight to the decompiler without re-decompressing.
    """
    code = compile(source, "<test>", "exec")
    raw = marshal.dumps(code)
    # We compress+decompress just to verify our zlib path works end-to-end.
    compressed = zlib.compress(raw, wbits=15)
    decompressed = zlib.decompress(compressed)
    b64 = base64.b64encode(decompressed).decode("ascii")
    return f'# __SigilCodeObjectMarker__:{b64}\n'


@pytest.fixture
def l3_zlib_marshal_py(tmp_workdir: pathlib.Path, arithmetic_py: pathlib.Path) -> pathlib.Path:
    """An L3-wrapped .py file (input to the unwrap stage)."""
    p = tmp_workdir / "l3_zlib_marshal.py"
    p.write_text(_zlib_marshal_wrapper_source(arithmetic_py.read_text(encoding="utf-8")),
                 encoding="utf-8")
    return p


@pytest.fixture
def l3_zlib_marshal_marker(tmp_workdir: pathlib.Path, arithmetic_py: pathlib.Path) -> pathlib.Path:
    """A .py file whose body is a SigilCodeObjectMarker line (L3 payload)."""
    p = tmp_workdir / "l3_zlib_marshal_marker.py"
    p.write_text(_zlib_marshal_marker_text(arithmetic_py.read_text(encoding="utf-8")),
                 encoding="utf-8")
    return p
    return p


# ---------------------------------------------------------------------------
# L6 (.pyc) fixture: a real 3.13 .pyc built from the arithmetic source
# ---------------------------------------------------------------------------

# 3.13 magic: b"\x2b\x0e\x0d\x0a" (matches Python 3.13.x at the time of writing)
PYC_MAGIC_3_13 = b"\x2b\x0e\x0d\x0a"


@pytest.fixture
def arithmetic_pyc_313(tmp_workdir: pathlib.Path, arithmetic_py: pathlib.Path) -> pathlib.Path:
    """Compile arithmetic_py to a .pyc under Python 3.14's interpreter.

    The magic number on disk is the *current interpreter's* magic, which
    is 3.14 magic in this venv.  The decompile stage will detect the
    magic and route to pylingual for 3.11+ or to dis-fallback if pylingual
    is not installed.
    """
    import py_compile
    p = tmp_workdir / "01_arithmetic.pyc"
    py_compile.compile(str(arithmetic_py), cfile=str(p), doraise=True)
    return p


# ---------------------------------------------------------------------------
# PyInstaller bundle fixture: a fake .exe with the PyInstaller magic
# ---------------------------------------------------------------------------

PYINSTALLER_MAGIC = b"MEI\014\013\012\013\016"


@pytest.fixture
def fake_pyinstaller_exe(tmp_workdir: pathlib.Path) -> pathlib.Path:
    """A binary file with the PyInstaller magic at offset 0 (not a real bundle)."""
    p = tmp_workdir / "fake_bundle.exe"
    p.write_bytes(PYINSTALLER_MAGIC + b"\x00" * 1024)
    return p


# ---------------------------------------------------------------------------
# Random binary fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def random_binary(tmp_workdir: pathlib.Path) -> pathlib.Path:
    """A binary file with no recognisable magic - should classify as 'unknown'."""
    p = tmp_workdir / "random.bin"
    p.write_bytes(b"\x00\xff\x42\x9a\x7c\xd3\x05\xee" * 64)
    return p


# ---------------------------------------------------------------------------
# Config fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def stripper_config(tmp_workdir: pathlib.Path, hello_py: pathlib.Path) -> object:
    """A default StripperConfig pointing at the hello.py fixture.

    The pylingual_model_path is set to a non-existent path: the routing
    logic in DECOMPILE checks for pylingual installation separately from
    the model path, so a missing model is a clean failure, not a crash.
    """
    from pyglimmer_toolkit.core.generic_python_stripper import StripperConfig
    return StripperConfig(
        target=hello_py,
        out_dir=tmp_workdir / "out",
        allow_dis_fallback=True,
    )
