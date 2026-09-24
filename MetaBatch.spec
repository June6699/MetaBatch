# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path


def _find_runtime_dll(filename: str) -> Path | None:
    candidates = [
        Path(sys.prefix) / "Lib" / "site-packages" / "PySide6" / filename,
        Path(sys.prefix) / filename,
    ]
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if directory.strip():
            candidates.append(Path(directory) / filename)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


# PySide6 6.11's Qt6Core.dll imports ICU by the generic DLL name.  Some
# Windows machines do not provide ICU in System32, so ship the exact runtime
# DLLs next to the PySide6 binaries inside the one-file archive.
qt_runtime_binaries = []
for _filename in ("icuuc.dll", "icudt78.dll"):
    _path = _find_runtime_dll(_filename)
    if _path is not None:
        qt_runtime_binaries.append((str(_path), "PySide6"))


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=qt_runtime_binaries,
    datas=[('assets', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['runtime_hooks/qt_dll_path.py'],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MetaBatch',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/metabatch_icon.ico'],
)
