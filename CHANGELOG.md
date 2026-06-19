# Changelog

All notable changes to pyglimmer-stripper are documented in this file.

## [0.0.1.dev1] — 2026-06-XX

### Fixed
- `PipelineResult.success` no longer hardcoded to `False`. The CLI
  `strip` and `pipeline` commands now exit 0 on a successful run.
- `decompile_with_pylingual` diagnostic prints moved from `print()`
  to the `logging` module (DEBUG level).

### Added
- Hypothesis property test: `unwrap_iter` is idempotent on the L1/L2/
  L3/L5 fixture set.
- PyInstaller extraction tests with a 100-byte synthetic fixture
  (no real .exe in the repo).
- `.gitignore` audit: `tools/pylingual_model/`, `tools/pycdc/`,
  `tools/pylingual/`, and `eval/report_*.json` now correctly ignored.
- Eval bench now reports `xfail` cases (pylingual v0.1.0 3.14
  dataclass bug) explicitly instead of counting them as failures.

### Known regressions
- 2 cases (17_generators, 20_dataclasses) still fail across L2, L3,
  and L6 due to pylingual v0.1.0's 3.14 dataclass bug. Tracked under
  Path 3 in `v2_ROADMAP.md`.

## [0.0.1.dev0] — 2026-06-18

Initial dev release. 94.4% behavior-preservation rate on the 20-case
x 5-layer eval bench. 76 pytest tests passing.
