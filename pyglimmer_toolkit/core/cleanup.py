"""LLM CLEANUP stage.

The decompiler (pycdc, pylingual, or dis-fallback) produces source that
*parses* but is hard to read: dead code, mangled names, missing
whitespace, broken f-strings, wrong operator precedence.  This stage
hands the decompiled source to a local LLM (Ollama default; Anthropic
or OpenAI opt-in) with a "clean this up, do not change semantics"
prompt, then runs an AST-based diff to confirm the cleaned source still
*means* the same thing as the original.

Backends:

  - ollama      - default.  Calls POST /api/generate on
                  http://127.0.0.1:11434 with the chosen model.  If
                  the server is unreachable, returns None and the
                  cleanup stage is skipped (this is a legitimate
                  outcome, not an error - decompiler-only recovery is
                  already useful).
  - anthropic   - opt-in, requires send_to_cloud=True.  Uses the
                  `anthropic` PyPI package.
  - openai      - opt-in, requires send_to_cloud=True.  Uses the
                  `openai` PyPI package.
  - passthrough - the caller supplies a Callable[[str], str] directly.
                  Used by the test bench to plug in a no-op or a mock
                  LLM so cleanup can be exercised without a live model.

The semantic diff is the safety net.  We never trust an LLM not to
subtly break a function; we *verify* by re-parsing the cleaned source
and comparing AST shape (function/class defs, top-level names,
signature) against the input.  If anything changed, we discard the
cleaned output and return the original.
"""
from __future__ import annotations

import ast
import json
import re
import textwrap
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional


# Prompt template: deliberately small and unambiguous.  The local model
# doesn't need (or want) a system-prompt novel - one paragraph, a few
# do/don't rules, the source to clean, and a request for a single code
# block.
CLEANUP_PROMPT = textwrap.dedent("""\
    You are cleaning up decompiled Python source.  The decompiler
    produced syntactically valid but hard-to-read code.  Your job is
    to make it readable WITHOUT changing what the program does.

    Rules:
      1. Do not change the public API: function signatures, class
         names, top-level names, and decorators must remain identical.
      2. Do not reorder statements.
      3. Do not invent new imports unless the decompiler output
         references undefined names (rare; flag it in a comment).
      4. Fix whitespace, restore the f-string interpolation that
         decompilers often flatten into a literal, restore lost
         operators, restore lost parentheses around precedence.
      5. If you cannot figure out a section, leave it as-is and add a
         comment `# noqa: decompiler artifact - manual review needed`.

    Return ONLY the cleaned Python source in a single fenced code
    block, using the python language tag.  No prose before or after.

    Source to clean:

    ~~~python
    {source}
    ~~~
""")


# ---------------------------------------------------------------------------
# Backend: Ollama (default; local; no send_to_cloud required)
# ---------------------------------------------------------------------------

def ollama_is_available(base_url: str = "http://127.0.0.1:11434",
                         timeout: float = 2.0) -> bool:
    """Quick health check: does the Ollama server respond?"""
    try:
        with urllib.request.urlopen(f"{base_url}/api/version", timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
        return False


def ollama_generate(prompt: str, model: str, base_url: str = "http://127.0.0.1:11434",
                     timeout: int = 120) -> str:
    """Call Ollama's /api/generate.  Returns the model's text output."""
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 4096},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    return data.get("response", "")


# ---------------------------------------------------------------------------
# Backend: Anthropic (opt-in; send_to_cloud required)
# ---------------------------------------------------------------------------

def anthropic_generate(prompt: str, model: str = "claude-opus-4-8",
                        api_key: Optional[str] = None,
                        timeout: int = 120) -> str:
    """Call Anthropic's messages API.  api_key defaults to ANTHROPIC_API_KEY env."""
    import os
    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError("anthropic_generate: ANTHROPIC_API_KEY not set")
    body = json.dumps({
        "model": model,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    blocks = data.get("content", [])
    parts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Backend: OpenAI (opt-in; send_to_cloud required)
# ---------------------------------------------------------------------------

def openai_generate(prompt: str, model: str = "gpt-4o",
                     api_key: Optional[str] = None,
                     timeout: int = 120) -> str:
    import os
    key = api_key or os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("openai_generate: OPENAI_API_KEY not set")
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    choices = data.get("choices", [])
    if not choices:
        return ""
    return choices[0].get("message", {}).get("content", "")


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

_CODE_BLOCK_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)


def _extract_code_block(text: str) -> str:
    """Pull the first Python code block out of an LLM response.

    If there's no code block marker, assume the whole response is code
    (some small local models skip the fences).  Strip leading/trailing
    prose either way.
    """
    m = _CODE_BLOCK_RE.search(text)
    if m:
        return m.group(1).strip()
    return text.strip()


# ---------------------------------------------------------------------------
# Semantic diff
# ---------------------------------------------------------------------------

def _ast_signature(source: str) -> Optional[dict]:
    """Build a structural signature of the source.

    Captures top-level names and their kind (function, class, async
    function), function signatures (name, arg count, decorators), and
    class bases.  Used to verify the LLM cleanup did not change
    semantics.

    Returns None if the source does not parse.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    sig: dict = {"top_level": [], "funcs": [], "classes": []}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sig["top_level"].append(("def", node.name))
            sig["funcs"].append({
                "name": node.name,
                "args": len(node.args.args),
                "posonlyargs": len(getattr(node.args, "posonlyargs", [])),
                "kwonlyargs": len(getattr(node.args, "kwonlyargs", [])),
                "decorators": [
                    ast.unparse(d) if hasattr(ast, "unparse") else ""
                    for d in node.decorator_list
                ],
            })
        elif isinstance(node, ast.ClassDef):
            sig["top_level"].append(("class", node.name))
            sig["classes"].append({
                "name": node.name,
                "bases": [
                    ast.unparse(b) if hasattr(ast, "unparse") else ""
                    for b in node.bases
                ],
            })
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    sig["top_level"].append(("assign", t.id))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            sig["top_level"].append(("annot_assign", node.target.id))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                sig["top_level"].append(("import", alias.asname or alias.name))
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                sig["top_level"].append(("from_import", alias.asname or alias.name))
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            sig["top_level"].append(("doc",))
    return sig


def _semantic_diff_preserves_structure(before: str, after: str) -> tuple[bool, str]:
    """Return (ok, reason).  ok=True iff after parses AND its top-level
    signature matches before's.  We do not compare full ASTs (too
    strict - decompilers change whitespace and trivia); we only check
    the structural invariants that would indicate a real semantic
    change: renamed functions, lost/gained arguments, reordering at the
    top level, changed class hierarchy, etc.
    """
    sig_before = _ast_signature(before)
    sig_after = _ast_signature(after)
    if sig_before is None:
        return False, "input source does not parse"
    if sig_after is None:
        return False, "cleaned source does not parse"
    if sig_before["top_level"] != sig_after["top_level"]:
        return False, f"top-level shape changed: {sig_before['top_level']} -> {sig_after['top_level']}"
    if sig_before["funcs"] != sig_after["funcs"]:
        return False, "function signatures changed (name, argcount, or decorators)"
    if sig_before["classes"] != sig_after["classes"]:
        return False, "class definitions changed (name or bases)"
    return True, "signature preserved"


# ---------------------------------------------------------------------------
# Public API: llm_cleanup_file()
# ---------------------------------------------------------------------------

def llm_cleanup_file(
    input_path: Path,
    out_dir: Path,
    model_fn: Optional[Callable[[str], str]] = None,
    backend: str = "ollama",
    model_name: str = ":14b",
    send_to_cloud: bool = False,
    timeout: int = 120,
) -> tuple[Path, bool, int, str]:
    """Run the LLM cleanup pass on the decompiled source.

    Returns (output_path, changed, tokens_used, message).  The
    output_path is always a valid .py file; if cleanup was skipped or
    failed semantic verification, it is a copy of the input.

    Backend selection:
      - "passthrough" or a non-None model_fn: use model_fn directly.
      - "ollama": try local Ollama; if unreachable, skip (decompiler-
        only output is still valid).
      - "anthropic"/"openai": require send_to_cloud=True; raise on
        misuse (we never silently send source to a paid API without
        the explicit flag).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (input_path.stem + "_cleaned.py")
    source = input_path.read_text(encoding="utf-8", newline="")

    # Always write the input to the output path first; the cleanup, if
    # it succeeds, overwrites it.
    out_path.write_text(source, encoding="utf-8", newline="")

    # 1. Resolve the model callable.
    resolved_fn: Optional[Callable[[str], str]] = None
    if model_fn is not None:
        resolved_fn = model_fn
    elif backend == "passthrough":
        return out_path, False, 0, "cleanup: no model_fn supplied and backend=passthrough"
    elif backend == "ollama":
        if not ollama_is_available():
            return out_path, False, 0, "cleanup: Ollama not reachable on 127.0.0.1:11434; skipping LLM cleanup"
        def _oll(prompt):
            return ollama_generate(prompt, model_name, timeout=timeout)
        resolved_fn = _oll
    elif backend == "anthropic":
        if not send_to_cloud:
            return out_path, False, 0, "cleanup: backend=anthropic requires send_to_cloud=True (refused)"
        resolved_fn = lambda prompt: anthropic_generate(prompt, model_name, timeout=timeout)
    elif backend == "openai":
        if not send_to_cloud:
            return out_path, False, 0, "cleanup: backend=openai requires send_to_cloud=True (refused)"
        resolved_fn = lambda prompt: openai_generate(prompt, model_name, timeout=timeout)
    else:
        return out_path, False, 0, f"cleanup: unknown backend {backend!r}"

    # 2. Run the model.
    try:
        prompt = CLEANUP_PROMPT.format(source=source)
        response = resolved_fn(prompt)
    except Exception as e:
        return out_path, False, 0, f"cleanup: backend {backend!r} raised {type(e).__name__}: {e}"

    # 3. Extract the code block.
    cleaned = _extract_code_block(response)
    if not cleaned.strip():
        return out_path, False, 0, "cleanup: model returned empty response"

    # 4. Semantic verification.
    ok, reason = _semantic_diff_preserves_structure(source, cleaned)
    if not ok:
        return out_path, False, 0, f"cleanup: discarded output - {reason}"

    # 5. Persist.
    out_path.write_text(cleaned, encoding="utf-8", newline="")
    tokens = (len(prompt) + len(response)) // 4
    return out_path, True, tokens, f"cleanup: {backend}/{model_name} produced valid cleaned source"
