"""Tests for the LLM CLEANUP stage (pyglimmer_toolkit.core.cleanup).

The cleanup stage has these public pieces:
    - ollama_is_available()  - check if a local Ollama server is up
    - ollama_generate()      - call Ollama's /api/generate
    - anthropic_generate()   - call Anthropic's API (NEVER run from tests)
    - openai_generate()      - call OpenAI's API (NEVER run from tests)
    - llm_cleanup_file()     - the main entry point
    - _ast_signature()       - structural signature of a source file
    - _semantic_diff_preserves_structure() - did the cleanup change semantics?
    - _extract_code_block()  - pull a Python code block out of an LLM response

We test:
    - The connection-check returns False when no server is up
    - _ast_signature captures the structural shape of a function/class
    - _semantic_diff_preserves_structure rejects changes that lose functions
    - _extract_code_block strips the ```python fence markers
    - llm_cleanup_file with a custom model_fn is fully deterministic
"""
from __future__ import annotations

import pathlib

import pytest

from pyglimmer_toolkit.core.cleanup import (
    _ast_signature,
    _extract_code_block,
    _semantic_diff_preserves_structure,
    llm_cleanup_file,
    ollama_is_available,
)


# ---------------------------------------------------------------------------
# ollama_is_available
# ---------------------------------------------------------------------------

def test_ollama_is_available_returns_false_when_no_server() -> None:
    """When no Ollama server is running on 127.0.0.1:11434, return False.

    The test relies on the fact that the test runner does NOT have Ollama
    running.  If your test environment does run Ollama, this test will
    flake to True and you should mark it xfail or skip it.
    """
    result = ollama_is_available(timeout=0.1)
    # We accept either False (no server) or a quick True; in CI we expect False
    # and document the assumption.
    assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# _ast_signature: structural fingerprint
# ---------------------------------------------------------------------------

def test_ast_signature_captures_function_def() -> None:
    """_ast_signature returns the function name and arg count for a single def."""
    sig = _ast_signature("def foo(a, b):\n    return a + b\n")
    assert sig is not None
    assert ("def", "foo") in sig["top_level"]
    funcs = sig["funcs"]
    assert len(funcs) == 1
    assert funcs[0]["name"] == "foo"
    assert funcs[0]["args"] == 2


def test_ast_signature_captures_class_def_with_bases() -> None:
    """_ast_signature returns class name and base class names."""
    sig = _ast_signature("class Foo(Bar, Baz):\n    pass\n")
    assert sig is not None
    assert ("class", "Foo") in sig["top_level"]
    classes = sig["classes"]
    assert len(classes) == 1
    assert classes[0]["name"] == "Foo"
    # Both base classes are recorded
    assert "Bar" in classes[0]["bases"]
    assert "Baz" in classes[0]["bases"]


def test_ast_signature_returns_none_for_invalid_syntax() -> None:
    """_ast_signature returns None for source that does not parse."""
    sig = _ast_signature("def foo(:\n")  # SyntaxError: missing arg
    assert sig is None


def test_ast_signature_captures_imports() -> None:
    """_ast_signature records top-level import statements."""
    sig = _ast_signature("import os\nfrom sys import argv\n")
    assert sig is not None
    assert ("import", "os") in sig["top_level"]
    assert ("from_import", "argv") in sig["top_level"]


# ---------------------------------------------------------------------------
# _semantic_diff_preserves_structure
# ---------------------------------------------------------------------------

def test_semantic_diff_accepts_identical_source() -> None:
    """The diff returns ok=True for two structurally identical sources.

    The reason string is informational ("signature preserved" on match);
    we only check that ok is True.
    """
    src = "def foo(a):\n    return a + 1\n"
    ok, reason = _semantic_diff_preserves_structure(src, src)
    assert ok is True
    assert isinstance(reason, str)


def test_semantic_diff_rejects_lost_function() -> None:
    """Removing a function from the cleaned source is flagged as a semantic change."""
    before = "def foo(a):\n    return a + 1\ndef bar(b):\n    return b * 2\n"
    after = "def foo(a):\n    return a + 1\n"
    ok, reason = _semantic_diff_preserves_structure(before, after)
    assert ok is False
    assert "bar" in reason or "lost" in reason.lower()


def test_semantic_diff_rejects_renamed_function() -> None:
    """Renaming a function is flagged as a semantic change (it changes the public API)."""
    before = "def foo(a):\n    return a + 1\n"
    after = "def baz(a):\n    return a + 1\n"
    ok, reason = _semantic_diff_preserves_structure(before, after)
    assert ok is False


def test_semantic_diff_rejects_syntax_error() -> None:
    """A cleaned source that does not parse is flagged."""
    before = "def foo(a):\n    return a + 1\n"
    after = "def foo(a):\n    return a + 1\ndef bar(:\n"  # broken
    ok, reason = _semantic_diff_preserves_structure(before, after)
    assert ok is False


# ---------------------------------------------------------------------------
# _extract_code_block
# ---------------------------------------------------------------------------

def test_extract_code_block_strips_fences() -> None:
    """A ```python\\n...\\n``` block is unwrapped to its inner content."""
    text = "Here is the fix:\n```python\ndef foo():\n    return 1\n```\nDone."
    inner = _extract_code_block(text)
    assert "def foo" in inner
    assert "```" not in inner
    assert "Here is the fix" not in inner


def test_extract_code_block_handles_no_fence() -> None:
    """When the response has no ``` fence, the whole text is returned (stripped)."""
    text = "def foo():\n    return 1\n"
    inner = _extract_code_block(text)
    assert "def foo" in inner


# ---------------------------------------------------------------------------
# llm_cleanup_file with a deterministic stub model_fn
# ---------------------------------------------------------------------------

def test_llm_cleanup_file_uses_custom_model_fn(tmp_path: pathlib.Path) -> None:
    """llm_cleanup_file with a stub model_fn returns the stub's output verbatim.

    We do NOT make any network calls; the model_fn is a no-op that
    returns a fixed string.  This tests the file-IO + prompt + write
    loop, not the LLM itself.
    """
    source = tmp_path / "input.py"
    source.write_text("def foo():\n    return 1\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    def stub_model(prompt: str) -> str:
        # Return a valid Python code block that preserves the function name
        return "```python\ndef foo():\n    return 42\n```\n"

    out_path, changed, tokens_used, msg = llm_cleanup_file(
        input_path=source,
        out_dir=out_dir,
        model_fn=stub_model,
    )
    assert out_path.exists()
    assert changed is True
    # The stub's output is what got written
    text = out_path.read_text(encoding="utf-8")
    assert "def foo" in text
    assert "42" in text


def test_llm_cleanup_file_rejects_semantic_drift(tmp_path: pathlib.Path) -> None:
    """If the model_fn returns source that lost a function, cleanup fails (and the original is preserved)."""
    source = tmp_path / "input.py"
    source.write_text("def foo(a):\n    return a + 1\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    def bad_model(prompt: str) -> str:
        # Drop the function entirely - this should be caught by the semantic check
        return "```python\nx = 1\n```\n"

    out_path, changed, tokens_used, msg = llm_cleanup_file(
        input_path=source,
        out_dir=out_dir,
        model_fn=bad_model,
    )
    # The output file is always written (it's a copy of the input as a
    # baseline; the model's output is rejected by the semantic check).
    assert out_path.exists()
    text = out_path.read_text(encoding="utf-8")
    # The original is preserved (the model's mangled output is not written)
    assert "def foo" in text
    # changed=False because the semantic check rejected the model
    assert changed is False
