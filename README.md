# pyglimmer-stripper

> Generic Python obfuscation stripper with optional LLM cleanup. Extracts, unwraps, decompiles, and cleans `.pyc` and PyInstaller-bundled `.exe` files.

## Honest Status

This is a **scaffolded skeleton**, not a working product. The CLI entry point
works (`python -m pyglimmer_stripper --help` returns help text), the architecture
is in place, and CI is wired up. The actual deobfuscation logic in each module
is `TODO` — every stage method currently returns a placeholder result.

The `.NET` and `PyArmor` pillars that earlier drafts promised are **deferred to
v2**. See `05_ADVERSARIAL_REVIEW.md` for the full rationale. The skeleton keeps
those modules as `deferred` seeds, not shipped features.

Before implementation begins, see `09_OPEN_QUESTIONS.md` for the eight decisions
the project owner (LO) must make.

## What works right now

- [x] Project layout (`pyglimmer_stripper/` package with `core/`, `gui/`, `utils/`)
- [x] CLI entry point — `python -m pyglimmer_stripper --help` returns help text
- [x] Typer + Rich CLI scaffold
- [x] Single-pillar four-stage pipeline (extract → unwrap → decompile → llm_cleanup)
      with Pydantic-validated stage results
- [x] Target-kind auto-detection (`.py` / `.pyc` / PyInstaller bundle / unknown)
- [x] PyInstaller spec (valid syntax; ready for `pyinstaller pyinstaller.spec`)
- [x] GitHub Actions: test (3 OS), lint (ruff + mypy), eval (corpus), release (.exe + PyPI)

## What is NOT done

- [ ] All `core/*.py` internals — every stage method returns a placeholder result
- [ ] Decompiler subprocess integration (pycdc, pylingual)
- [ ] AST unwrap pipeline (base64 / marshal / zlib / lambda layers)
- [ ] LLM cleanup pass (Ollama local default; Anthropic/OpenAI gated)
- [ ] Eval harness with the obfuscation corpus (`eval/corpus/`, `eval/run_eval.py`)
- [ ] GUI (deferred to v1.1)
- [ ] Sample obfuscated test fixtures in `samples/`
- [ ] Documentation site under `docs/`
- [ ] Test suite under `tests/` (the directory exists but is empty)

## Scope (v1)

Ship **one** pillar: the generic Python stripper. CLI-only. PyPI distribution.

Explicitly **out of scope for v1**, deferred to v2 contingent on user demand:

- `.NET` deobfuscation pillar (de4dot is archived, ecosystem is in maintenance
  mode, AsmResolver v5→v6 has 8 breaking changes)
- `PyArmor` unwrapping (Lil-House's v0.4.0 supports PyArmor 8.0–9.2.5 and is
  being rewritten in 2027; a wrapper has a 12–18 month half-life)
- GUI (PySide6 + QScintilla)
- Windows `.exe` distribution (PyInstaller build IS shipped in v1; the
  full GUI bundle ships in v1.1)

## Quick Start (Developer)

```bash
# Clone, then:
python -m venv .venv
source .venv/bin/activate          # or .venv\Scripts\activate on Windows
pip install -e ".[dev,decompilers,llm,test]"

# Verify the CLI works:
python -m pyglimmer_stripper --help

# Run tests (skeleton passes; module internals return placeholders):
pytest tests/ -v

# Build a Windows .exe (after internals are implemented):
pyinstaller pyinstaller.spec
```

## Architecture

```
pyglimmer_stripper/
├── __main__.py        # Entry point: `python -m pyglimmer_stripper`
├── cli.py             # Typer app, top-level `pyglimmer` command
├── core/
│   ├── generic_python_stripper.py  # The single v1 pillar (extract → unwrap → decompile → llm_cleanup)
│   ├── pipeline.py                 # Single-pillar orchestrator with target-kind auto-detect
│   ├── pyarmor_unpacker.py         # v2 SEED — module is not exported (`__all__ = []`)
│   └── dotnet_deobfuscator.py      # v2 SEED — module raises NotImplementedError on import
├── gui/               # v1.1 (PySide6 + QScintilla)
└── utils/
    ├── hashing.py     # SHA-256 for cache keys
    └── process.py     # Subprocess management with cancellation
```

## License

**GPL-3.0-or-later.** Forced by the dependency tree — QScintilla (GPL-3.0 OR
commercial), pylingual (GPL-3.0), Lil-House/Pyarmor-Static-Unpack-1shot (GPL-3.0),
plus the multiple GPL-3.0-compatible decompilers in the substrate. Subprocess-only
architecture (we never import decompilers as Python modules) keeps the wrapper
compatible with downstream permissive consumers at the output end, but the
project itself is GPL-3.0.

If a permissive license (MIT or Apache-2.0) is required, several dependencies
must be swapped or removed. See `09_OPEN_QUESTIONS.md` Q3.

## Verified fact corrections

- **Nuitka is v4.1.2 / AGPL-3.0**, not v2.7.15 / Apache-2.0. The original draft's
  "migrate to Nuitka in v1.1" plan is OFF the table. PyInstaller 6.21.0 is the
  v1 and v1.1 .exe builder.
- **Azure Trusted Signing was rebranded to Azure Artifact Signing.** Pricing
  unconfirmed. Confirm before the first signed release.

## See Also

- `../00_EXECUTIVE_SUMMARY.md` — 1-page verdict
- `../01_PYGLIMMER_AUDIT.md` — what the original PyGlimmer project is
- `../02_LANDSCAPE_MAP.md` — the surrounding tool ecosystem
- `../03_FEATURE_FEASIBILITY.md` — per-feature deep-dives
- `../04_LEGAL_AND_SAFETY.md` — DMCA / EU InfoSoc posture
- `../05_ADVERSARIAL_REVIEW.md` — the build/pivot/drop verdict
- `../06_VERIFIED_FACTS.md` — sourced facts, including 3 failed claims
- `../07_ROADMAP.md` — phased build plan
- `../09_OPEN_QUESTIONS.md` — eight decisions the user must make
