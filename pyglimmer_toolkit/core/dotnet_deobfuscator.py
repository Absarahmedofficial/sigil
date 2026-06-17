"""Deferred to v2.

The .NET deobfuscation pillar was dropped from v1 per `05_ADVERSARIAL_REVIEW.md`.
Rationale (compressed):

  - de4dot (the de facto .NET deobfuscator reference) is archived as of 2020-10-17.
  - ConfuserExMod and .NET Reactor ship new variants faster than the deobfuscator
    ecosystem can keep up. Custom passes rot.
  - AsmResolver v5->v6 has 8 breaking changes, documented at
    https://docs.washi.dev/asmresolver/guides/migration-v5-v6.html
  - The .NET sidecar is 9-14 weeks of solo-dev effort (per Standish CHAOS 1.5x
    multiplier) and adds ~150MB to the binary for a feature no v1 user has
    asked for.
  - Maintenance half-life is worse than PyArmor: when .NET 10 / NativeAOT
    changes the bytecode model, the wrapper is dead code.

If this pillar is ever revived (v2+), the substrate is:

  - ILSpy v10.1 (MIT)            -- the decompiler
  - AsmResolver v6.0.0 (MIT)     -- the assembly reader/writer
  - dnlib (MIT)                  -- metadata + low-level manipulation
  - ICSharpCode.Decompiler (MIT) -- IL -> C# decompilation
  - Custom passes for: string decryption, ConfuserExMod CFG unflattening,
    reference-proxy resolution

Architecture: separate C# sidecar process, NDJSON-over-stdin/stdout IPC, async
Python wrapper. The wrapper subprocess invokes dotnet to run the sidecar.

This module is intentionally a stub. Importing it raises immediately so
callers know to wait for v2.
"""

from __future__ import annotations


def not_implemented() -> None:
    """Raise NotImplementedError. The .NET pillar is deferred to v2."""
    raise NotImplementedError(
        "The .NET deobfuscation pillar is deferred to v2. "
        "See pyglimmer_research/05_ADVERSARIAL_REVIEW.md section 5 ('Things to drop entirely') "
        "and 09_OPEN_QUESTIONS.md Q2 for the rationale."
    )
