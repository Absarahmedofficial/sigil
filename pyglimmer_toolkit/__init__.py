"""PyGlimmer-Toolkit: reverse-engineering toolkit.

Three pillars:
    - PyArmor unpacker (wraps Lil-House/Pyarmor-Static-Unpack-1shot)
    - .NET deobfuscator (sidecar IPC to a C# .NET 8 process)
    - Generic Python stripper (pycdc + pylingual + LLM cleanup)

License: GPL-3.0-or-later (forced by QScintilla GPL + GPL-3.0 decompiler deps).
"""

from __future__ import annotations

__version__ = "0.0.1.dev0"
__license__ = "GPL-3.0-or-later"

__all__ = ["__version__", "__license__"]
