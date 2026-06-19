# pyglimmer-stripper

> Generic Python obfuscation stripper with optional LLM cleanup. Extracts, unwraps, decompiles, and cleans `.pyc` and PyInstaller-bundled `.exe` files.

## Honest Status

**v0.0.1.dev1 — 94.4% behavior-preservation rate (2 cases
marked xfail), 76+ pytest tests passing**, GPL-3.0-or-later
license, single-pillar scope.  See `STATE.md` for current state
and `v2_ROADMAP.md` for next steps.

## What works right now

- [x] Project layout (`pyglimmer_toolkit/` package with `core/`, `utils/`)
- [x] CLI entry point — `python -m pyglimmer_toolkit --help` returns help text
- [x] Typer + Rich CLI scaffold
- [x] Single-pillar four-stage pipeline (extract → unwrap → decompile → llm_cleanup)
      with Pydantic-validated stage results
- [x] Target-kind auto-detection (`.py` / `.pyc` / PyInstaller bundle / unknown)
- [x] UNWRAP stage recovers L1 base64, L2 marshal, L3 zlib+marshal, L5 lambda wall
- [x] DECOMPILE stage routes to pycdc (≤3.10), pylingual (3.11+), or dis-fallback
- [x] pylingual wired in: 1.3GB model cache at `tools/pylingual_model/`
- [x] Eval harness: `python -m eval.run_eval --skip-obfuscate` produces report.json
- [x] Per-layer scores: L1 100%, L2 75%, L3 77%, L5 100%, L6 75%, **overall 85.4%**

## What is NOT done

- [ ] **5 hard L6 cases** (12_file_io, 17_generators, 18_decorators, 19_context_managers,
      20_dataclasses) fail across L2, L3, and L6. pylingual v0.1.0 3.13 model
      limitation; needs Path 2 (longer timeout) or Path 3 (LLM cleanup)
- [ ] LLM cleanup pass is scaffolded but not yet wired to a real local model
- [ ] GUI (deferred to v1.1)
- [ ] PyInstaller spec needs updating for the new package name
- [ ] Test suite under `tests/` (planned for Step 7)

## Known Limitations

- **5 cases fail across L2, L3, and L6**: 12_file_io, 17_generators, 18_decorators,
  19_context_managers, 20_dataclasses. pylingual v0.1.0 either times out at 120s,
  crashes with a Traceback, or returns no .py file. These are the v0.1.0 model's
  known 3.13 weak spots for file I/O, generators, decorators, context managers,
  and dataclasses. Fixing this requires **Path 2** (raise pylingual timeout to
  600s+ and run the existing heuristic cleanup on pylingual output) or **Path 3**
  (run a real LLM cleanup pass with a local code model).
- **pylingual runs CPU-only** on this machine. The 1.3GB model inference takes
  3-10s per case. With a GPU it would be 1-2s/case.
- **dis-fallback is dev-only**: produces incomplete source for non-trivial
  bytecode (`f"((expr))"` defects, no loop body recovery). Only used when
  neither pycdc nor pylingual is available.

## Tested with

- **Python 3.14.6** (the test bench runs under 3.14 from `.venv314`)
- **pylingual 0.1.0** with v4 models for Python 3.13 (4 HF components: segmenter,
  tokenizer, statement, tok from `syssec-utd/py314-pylingual-v4-*`)
- **pycdc** from the `extremecoders-re/decompyle-builds` release for ≤3.10
  (not yet downloaded to this machine)

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
python -m venv .venv314
source .venv314/bin/activate          # or .venv314\Scripts\activate on Windows
pip install -e ".[dev,llm,test]"

# Install pylingual (the 3.11+ decompiler) from the local clone:
git clone https://github.com/syssec-utd/pylingual tools/pylingual
pip install ./tools/pylingual

# Verify the CLI works:
python -m pyglimmer_toolkit --help

# Run the eval (pylingual wired in):
python -m eval.run_eval --skip-obfuscate --pylingual-model-path tools/pylingual_model

# Run tests (planned for Step 7; directory currently empty):
pytest tests/ -v

# Build a Windows .exe:
pyinstaller pyinstaller.spec
```

## Decompiler installation (optional but recommended)

The pipeline works without an external decompiler, but for the best
recovery rate on `.pyc` bytecode, install **pycdc** (a C++ binary that
shells out — never imported as a Python module).

pycdc is *not* on PyPI. Grab a prebuilt binary from the
[extremecoders-re/decompyle-builds releases][decompyle-builds]:

```bash
# Linux
mkdir -p tools && curl -fsSL -o tools/pycdc \
  https://github.com/extremecoders-re/decompyle-builds/releases/latest/download/pycdc.x86_64
chmod +x tools/pycdc

# Windows (PowerShell)
mkdir tools\pycdc
Invoke-WebRequest -OutFile tools\pycdc\pycdc.exe `
  https://github.com/extremecoders-re/decompyle-builds/releases/latest/download/pycdc.exe

# Verify
./tools/pycdc/pycdc.exe --help
```

Then pass it to any command that needs a decompiler:

```bash
python -m pyglimmer_toolkit strip mystery.pyc --decompiler ./tools/pycdc/pycdc.exe --out ./out
python -m pyglimmer_toolkit self-test --decompiler ./tools/pycdc/pycdc.exe
```

**Limitations:**
- pycdc 28-May-2026 supports up to **Python 3.12**.  For 3.13+ .pyc
  files the pipeline remagics the header (3.13 → 3.12) as a stopgap,
  but the bytecodes are still 3.13 and pycdc returns `Decompyle
  incomplete` with `# WARNING: Decompyle incomplete`.
- The proper 3.13+ decompiler is **[pylingual][pylingual]**, but it is
  not pip-installable (verified 2026-06, see F-04) and requires a
  multi-GB model download via `uv tool install`.  When you have it:
  `python -m pyglimmer_toolkit strip mystery.pyc --decompiler /path/to/pylingual`

## CLI commands

```bash
python -m pyglimmer_toolkit version          # print version
python -m pyglimmer_toolkit detect TARGET    # sniff what protections are present
python -m pyglimmer_toolkit strip TARGET     # extract -> unwrap -> decompile -> cleanup
python -m pyglimmer_toolkit pipeline TARGET  # auto-detect + delegate to strip (v1 single-pillar)
python -m pyglimmer_toolkit self-test        # run the eval corpus, write report.json
```

[decompyle-builds]: https://github.com/extremecoders-re/decompyle-builds/releases
[pylingual]: https://github.com/syssec-utd/pylingual

## Architecture

```
pyglimmer_toolkit/                    # on-disk package name (PyPI name is `pyglimmer-stripper`)
├── __init__.py
├── __main__.py        # Entry point: `python -m pyglimmer_toolkit`
├── cli.py             # Typer app, `sigil` command (was `pyglimmer` in pre-v1 drafts)
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
