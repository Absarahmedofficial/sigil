# v2 Roadmap — backlog after v0.1.0

This file lists what we are *not* shipping in v0.1.0, and the
order we plan to attack it.  Every item below is scoped as its own
research/design doc in `research/` before any code lands.

## Priority 1 (deferred from v0.0.1.dev0)

* **PyArmor support** — see `research/PYARMOR_RESEARCH.md`.
  PyArmored samples cannot currently be handled by the generic
  Python stripper.  The deobfuscation work either goes through
  Lil-House's `pyarmor-static-unpack-1shot` (with its 12-18 month
  half-life) or a sandbox-and-dump approach with associated
  malware-handling risk.  Verdict from research doc drives whether
  this lands in v2 or is skipped.

* **Path 3: real LLM cleanup** — see `research/LLM_CLEANUP_RESEARCH.md`.
  The current `_heuristic_cleanup_model` is a deterministic fallback
  that catches the dis-fallback `(expr) -> ((expr))` defect and is a
  no-op for clean pylingual output.  A real LLM backend (Ollama
  Codellama 13B / 14B) could in principle recover the dataclass
  definitions that pylingual v0.1.0 cannot decompile (cases 17 and
  20).  Would push the score above 94.4% on the eval bench.

* **PyInstaller extraction tests** — `core/extract.py:sniff()` is
  supposed to detect PyInstaller bundles by the `MAGIC` cookie, and
  the eval bench already has a `pyinstaller` layer slot reserved.
  We have no `.exe` fixture yet.  v2 task: write a PyInstaller
  fixture generator, add `test_extract_pyinstaller.py`, and wire
  PyInstaller bundles into the eval bench as a new layer family.

* **GUI (v1.1, not v2)** — `pyglimmer_toolkit/gui/` is currently
  an empty package.  v1.1 brings PySide6 + QScintilla for a
  code-editor view of the decompiled source.  Tracked here for
  visibility; not on the v2 critical path.

## Priority 2 (v0.0.1.dev0 leftovers)

* **Fix `PipelineResult.success = False` hardcode.**
  `core/generic_python_stripper.py:run_pipeline` hardcodes the
  success flag to `False`.  The CLI `strip` and `pipeline`
  commands therefore always exit 1.  The fix is mechanical: derive
  `success` from `decompile_result.success` (and `extract.success`
  and `unwrap.success`, all of which are real pydantic fields
  today).  Trivial to write; trivial to test; just needs to land.

* **Move `decompile_with_pylingual` debug prints to `logging`.**
  The function currently writes `DEBUG: pylingual_cmd is None!` and
  `DEBUG: trying pylingual with cmd=...` to stdout when pylingual
  is not installed.  This is v0.0.1.dev0 diagnostic noise.  Should
  be moved to the `logging` module so it goes to stderr (or
  `/dev/null` when logging is unconfigured).  v2 cleanup.

## Out of scope for both v0.1.0 and v2

* **.NET / IL deobfuscation.**  v1 was cut-scope to single-pillar.
  The `dotnet_deobfuscator.py` module is a `NotImplementedError`
  seed.  No v2 plan.
* **PyInstaller-native execution.**  We use `pyinstxtractor` for
  bundle unpacking, not PyInstaller itself.  v2 may add a
  PyInstaller-aware exec wrapper if the security review clears it.
* **GUI** (covered above, v1.1 not v2).

## How to use this doc

When you start work on a backlog item:

1. Read the corresponding `research/<TOPIC>_RESEARCH.md` first.
2. If no research doc exists, write one as your first deliverable.
3. The research doc must end with a **Verdict** (pursue / defer /
   skip) and a **Cost estimate** (hours, or a t-shirt size).
4. Only then do you open an implementation PR.

Do NOT open an implementation PR without a research doc.
