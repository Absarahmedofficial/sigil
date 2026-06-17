# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for pyglimmer-stripper.

Build a single-file Windows .exe via:

    pyinstaller pyinstaller.spec --clean --noconfirm

The output is `dist/pyglimmer-stripper.exe`. The release workflow
(.github/workflows/release.yml) signs, hashes, and uploads it.

Hidden imports are listed explicitly because PyInstaller's static analysis
sometimes misses dynamic imports (Typer's sub-app discovery, pydantic's
forward references, etc.).
"""

from pathlib import Path
import sys

block_cipher = None

# Project root and entry point.
PROJECT_ROOT = Path(SPECPATH).resolve()
sys.path.insert(0, str(PROJECT_ROOT))

# IMPORTANT: replace this with the actual package name once the rename is done
# in pyproject.toml. The skeleton uses pyglimmer_toolkit; the cut-scope
# verification says it should be pyglimmer_stripper. This spec supports both
# for the transition window.
PKG_NAME = "pyglimmer_stripper"  # post-rename
FALLBACK_PKG = "pyglimmer_toolkit"  # pre-rename (skeleton default)

try:
    from pyglimmer_stripper.__main__ import main as _pkg_main  # noqa: F401
    ENTRY_PKG = PKG_NAME
except ImportError:
    from pyglimmer_toolkit.__main__ import main as _pkg_main  # noqa: F401
    ENTRY_PKG = FALLBACK_PKG

a = Analysis(
    [f"{PROJECT_ROOT / ENTRY_PKG / '__main__.py'}"],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[
        # The default prompt template ships as a config file; bundled here.
        # Add real data files as the GUI ships. For v0.0.x (skeleton), this is empty.
    ],
    hiddenimports=[
        # Typer + Click internals that PyInstaller sometimes misses.
        "typer.main",
        "typer.core",
        "click",
        "click_plugins",
        # Rich has lazy-loaded backends.
        "rich.console",
        "rich.panel",
        "rich.table",
        "rich.progress",
        "rich.tree",
        # Pydantic v2 internals.
        "pydantic",
        "pydantic.fields",
        "pydantic.main",
        "pydantic.types",
        # Stdlib things we use but that the static analyzer misses.
        "importlib.metadata",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Pull in the pieces we don't need to keep the .exe small.
        "tkinter",
        "PySide6",  # v1 has no GUI. v1.1 adds PySide6 to hiddenimports.
        "PyQt6",
        "test",
        "unittest",
        "pylingual",  # subprocess-only; never imported
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="pyglimmer-stripper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # CLI tool; v1.1 GUI flips this to False + adds windowed bundle.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # v1.1 adds an icon asset.
)
