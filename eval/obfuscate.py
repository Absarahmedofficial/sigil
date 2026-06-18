"""Six-layer obfuscator (see module docstring for full details)."""
from __future__ import annotations

import argparse
import ast
import base64
import marshal
import pathlib
import sys
import textwrap
import zlib

ALL_LAYERS = [1, 2, 3, 4, 5, 6]
LAYER_FUNCS: dict = {}


def _compile_for_obfuscation(source: str) -> "code":
    """Compile source for embedding in a marshal payload.

    Forces ``co_flags == 0`` to match what ``py_compile`` produces and
    what pycdc understands.  Without this, when this module is loaded
    (it has ``from __future__ import annotations`` at the top), every
    ``compile()`` call inside it propagates CO_FUTURE_ANNOTATIONS
    (0x01000000) to the compiled code object.  pycdc chokes on that
    flag with "Decompyle incomplete" + a spurious "Unsupported opcode:
    CLEANUP_THROW" message, even though the bytecodes themselves are
    valid 3.12.

    We achieve clean flags by writing the source to a temp file and
    routing through ``py_compile`` (which always returns co_flags=0).
    The temp file is destroyed immediately after.
    """
    import py_compile
    import re as _re
    import tempfile as _tempfile
    import os as _os

    # Strip the leading future import if present (it's harmless but
    # saves a few bytes; py_compile would handle it fine anyway).
    cleaned = _re.sub(r"^\s*from\s+__future__\s+import\s+annotations\s*\n",
                      "", source, count=1, flags=_re.MULTILINE)

    # py_compile gives us a code object with co_flags == 0.
    fd, tmp_py = _tempfile.mkstemp(suffix=".py", prefix="sigil_compile_")
    try:
        with _os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(cleaned)
        fd_pyc, tmp_pyc = _tempfile.mkstemp(suffix=".pyc", prefix="sigil_compile_")
        try:
            _os.close(fd_pyc)
            py_compile.compile(tmp_py, cfile=tmp_pyc, doraise=True)
            import marshal as _marshal
            with open(tmp_pyc, "rb") as fh:
                data = fh.read()
            # pyc header is 16 bytes on Python 3.7+; skip it.
            co = _marshal.loads(data[16:])
            # py_compile stamps co_filename on EVERY nested code object
            # with the source path (a long Windows temp path that pycdc
            # chokes on).  Recursively rename them all to a short,
            # pycdc-friendly filename.
            return _rename_filenames(co, "<obfuscated>")
        finally:
            try:
                _os.unlink(tmp_pyc)
            except OSError:
                pass
    finally:
        try:
            _os.unlink(tmp_py)
        except OSError:
            pass


def _rename_filenames(co, new_name):
    """Recursively rename co_filename on a code object and all nested
    code objects in co_consts.  Returns a new code object (3.8+)."""
    new_consts = tuple(
        _rename_filenames(c, new_name) if hasattr(c, "co_code") else c
        for c in co.co_consts
    )
    return co.replace(co_filename=new_name, co_consts=new_consts)


def layer1_base64(source: str) -> str:
    encoded = base64.b64encode(source.encode("utf-8")).decode("ascii")
    return textwrap.dedent(f"""\
        import base64
        exec(base64.b64decode({encoded!r}).decode('utf-8'))
        """)


def layer2_marshal(source: str) -> str:
    code = _compile_for_obfuscation(source)
    payload = base64.b64encode(marshal.dumps(code)).decode("ascii")
    return textwrap.dedent(f"""\
        import base64, marshal
        exec(marshal.loads(base64.b64decode({payload!r})))
        """)


def layer3_zlib_marshal(source: str) -> str:
    code = _compile_for_obfuscation(source)
    payload = base64.b64encode(zlib.compress(marshal.dumps(code))).decode("ascii")
    return textwrap.dedent(f"""\
        import base64, marshal, zlib
        exec(marshal.loads(zlib.decompress(base64.b64decode({payload!r}))))
        """)


def layer4_rename(source: str) -> str:
    tree = ast.parse(source)
    counter = [0]

    def fresh_name() -> str:
        i = counter[0]
        counter[0] += 1
        if i < 26:
            return chr(ord("a") + i)
        first = (i // 26) - 1
        second = i % 26
        return chr(ord("a") + first) + chr(ord("a") + second)

    targets: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            targets.add(node.id)
        elif isinstance(node, ast.arg):
            targets.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            targets.add(node.name)
        elif isinstance(node, ast.ClassDef):
            targets.add(node.name)

    PRESERVE = {"__name__", "__main__", "__file__", "__builtins__", "self", "cls"}
    rename_map = {
        name: fresh_name() for name in targets
        if name not in PRESERVE and not name.startswith("__")
    }

    class Renamer(ast.NodeTransformer):
        def visit_Name(self, node):
            if node.id in rename_map:
                node.id = rename_map[node.id]
            return node

        def visit_arg(self, node):
            if node.arg in rename_map:
                node.arg = rename_map[node.arg]
            return node

        def visit_FunctionDef(self, node):
            if node.name in rename_map:
                node.name = rename_map[node.name]
            self.generic_visit(node)
            return node

        def visit_AsyncFunctionDef(self, node):
            if node.name in rename_map:
                node.name = rename_map[node.name]
            self.generic_visit(node)
            return node

        def visit_ClassDef(self, node):
            if node.name in rename_map:
                node.name = rename_map[node.name]
            for child in node.body:
                self.visit(child)
            return node

    renamed = Renamer().visit(tree)
    ast.fix_missing_locations(renamed)
    return ast.unparse(renamed)


def layer5_lambda_wall(source: str) -> str:
    tree = ast.parse(source)
    for stmt in tree.body:
        if isinstance(stmt, ast.Expr):
            inner_lambda = ast.Lambda(
                args=ast.arguments(
                    posonlyargs=[], args=[], kwonlyargs=[],
                    vararg=None, kwarg=None, kw_defaults=[], defaults=[],
                ),
                body=stmt.value,
            )
            call = ast.Call(func=inner_lambda, args=[], keywords=[])
            outer_lambda = ast.Lambda(
                args=ast.arguments(
                    posonlyargs=[], args=[], kwonlyargs=[],
                    vararg=None, kwarg=None, kw_defaults=[], defaults=[],
                ),
                body=call,
            )
            stmt.value = ast.Call(func=outer_lambda, args=[], keywords=[])
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def layer6_compile(source: str, dest: pathlib.Path) -> pathlib.Path:
    """Compile source to a real CPython .pyc (16-byte header + marshal payload).

    Uses the current interpreter's MAGIC_NUMBER so the file is roundtrippable:
    Stage 2's sniff() will recognize the magic, Stage 4's decompiler can read it.
    """
    import importlib.util
    import struct
    import time

    code = _compile_for_obfuscation(source)
    magic = importlib.util.MAGIC_NUMBER
    flags = 0  # unchecked-hash
    timestamp = int(time.time())
    source_size = 0  # PEP 552 unchecked-hash: source size is 0
    header = magic + struct.pack("<III", flags, timestamp, source_size)
    dest.write_bytes(header + marshal.dumps(code))
    return dest


LAYER_FUNCS.update({
    1: layer1_base64,
    2: layer2_marshal,
    3: layer3_zlib_marshal,
    4: layer4_rename,
    5: layer5_lambda_wall,
})


def parse_layers(spec: str):
    if spec == "all":
        return list(ALL_LAYERS)
    out = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        n = int(chunk)
        if n not in LAYER_FUNCS and n != 6:
            raise SystemExit(f"Unknown layer {n}; valid: {sorted(LAYER_FUNCS) + [6]}")
        out.append(n)
    return out


def apply_layers(input_path: pathlib.Path, layers, out_path: pathlib.Path) -> pathlib.Path:
    source = input_path.read_text(encoding="utf-8")
    current = source
    for n in layers:
        if n == 6:
            return layer6_compile(current, out_path.with_suffix(".pyc"))
        current = LAYER_FUNCS[n](current)
    out_path.write_text(current, encoding="utf-8")
    return out_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Apply obfuscation layers to a Python file.")
    parser.add_argument("input", type=pathlib.Path, help="Source .py file")
    parser.add_argument("-o", "--output", type=pathlib.Path, required=True, help="Output path")
    parser.add_argument("--layers", default="all", help="Comma-separated layer numbers, or 'all'")
    args = parser.parse_args(argv)

    if not args.input.is_file():
        parser.error(f"Input not found: {args.input}")

    layers = parse_layers(args.layers)
    result = apply_layers(args.input, layers, args.output)
    print(f"Wrote {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
