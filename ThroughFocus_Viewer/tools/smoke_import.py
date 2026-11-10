#!/usr/bin/env python3
"""Docs-install smoke check: required third-party + viewer imports.

Usage (from package root, with PYTHONPATH=src or after setup_env):
  python tools/smoke_import.py
"""
from __future__ import annotations

import importlib
import sys


REQUIRED = (
    "cv2",
    "scipy",
    "numpy",
    "openpyxl",
    "matplotlib",
    "PySide6",
)


def main() -> int:
    missing: list[str] = []
    for name in REQUIRED:
        try:
            importlib.import_module(name)
        except ImportError as exc:
            missing.append(f"{name}: {exc}")
    if missing:
        print("[FAIL] missing packages:", file=sys.stderr)
        for line in missing:
            print(f"  - {line}", file=sys.stderr)
        print(
            "Install with: pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1
    try:
        from viewer.gui.main_window import MainWindow
        from viewer import __version__
    except ImportError as exc:
        print(f"[FAIL] viewer import: {exc}", file=sys.stderr)
        print("Set PYTHONPATH=src (or run from setup_env).", file=sys.stderr)
        return 1
    print(f"OK ThroughFocus_Viewer v{__version__} ({MainWindow.__name__})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())