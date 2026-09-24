"""Register bundled Qt and ICU DLL directories before importing PySide6."""

from __future__ import annotations

import os
import sys
from pathlib import Path


_dll_directory_handles = []

if getattr(sys, "frozen", False):
    _root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    # PyInstaller keeps shiboken6 in its own package directory while the
    # PySide6 extension modules live below ``PySide6``.  QtCore.pyd imports
    # shiboken6.abi3.dll, so both directories must be registered before the
    # first PySide6 import.
    for _directory in (_root / "PySide6", _root / "shiboken6", _root):
        if not _directory.is_dir():
            continue
        try:
            _dll_directory_handles.append(os.add_dll_directory(str(_directory)))
        except (AttributeError, OSError):
            pass
        os.environ["PATH"] = str(_directory) + os.pathsep + os.environ.get("PATH", "")
