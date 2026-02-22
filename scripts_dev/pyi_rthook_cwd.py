"""PyInstaller runtime hook: set working directory to the executable's directory.

This ensures that relative paths like ``models/yolo11n.pt`` resolve correctly
when the app is launched from a desktop shortcut or macOS Finder (where the
default CWD is often / or the user home, not the app bundle directory).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # For macOS .app: sys.executable == .../BirdStamp.app/Contents/MacOS/BirdStamp
    # For Windows onedir: sys.executable == .../BirdStamp/BirdStamp.exe
    app_dir = Path(sys.executable).resolve().parent
    os.chdir(app_dir)
