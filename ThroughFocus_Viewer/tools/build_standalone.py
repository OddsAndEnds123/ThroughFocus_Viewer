"""Build ThroughFocus_Viewer standalone Windows package (no Python install)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
# Sibling release tree under Release /
# 發行目錄位於 Release
OUT_ROOT = ROOT.parent / "Release" / "ThroughFocus_Viewer_Win64"
BUILD_DIR = ROOT / "build" / "pyinstaller"
SPEC_WORK = BUILD_DIR / "work"
DIST_WORK = BUILD_DIR / "dist"

# Conda/Windows DLLs often missed by PyInstaller for _ctypes
EXTRA_DLL_NAMES = (
    "ffi-8.dll",
    "ffi.dll",
    "libffi-8.dll",
    "libffi.dll",
)


def _conda_library_bin() -> Path:
    return Path(sys.prefix) / "Library" / "bin"


def _copy_extra_dlls(target_dir: Path) -> list[str]:
    bin_dir = _conda_library_bin()
    copied: list[str] = []
    if not bin_dir.is_dir():
        return copied
    for name in EXTRA_DLL_NAMES:
        src = bin_dir / name
        if src.is_file():
            for dest_dir in (target_dir, target_dir / "_internal"):
                dest_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest_dir / name)
            copied.append(name)
    return copied


def main() -> int:
    sys.path.insert(0, str(SRC))
    from viewer import __version__

    entry = SRC / "viewer" / "__main__.py"
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR, ignore_errors=True)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    add_binary_args: list[str] = []
    bin_dir = _conda_library_bin()
    for name in EXTRA_DLL_NAMES:
        src = bin_dir / name
        if src.is_file():
            # Windows PyInstaller separator is ;
            add_binary_args.extend(["--add-binary", f"{src};."])

    icon_ico = ROOT / "assets" / "ThroughFocus_Viewer.ico"
    icon_args: list[str] = []
    if icon_ico.is_file():
        icon_args = ["--icon", str(icon_ico)]

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name", "ThroughFocus_Viewer",
        "--paths", str(SRC),
        "--distpath", str(DIST_WORK),
        "--workpath", str(SPEC_WORK),
        "--specpath", str(BUILD_DIR),
        "--hidden-import", "viewer",
        "--hidden-import", "viewer.gui.main_window",
        "--hidden-import", "openpyxl",
        "--hidden-import", "openpyxl.drawing.image",
        "--hidden-import", "et_xmlfile",
        "--collect-all", "openpyxl",
        "--collect-all", "et_xmlfile",
        "--hidden-import", "PIL",
        "--exclude-module", "PySide6.QtQml",
        "--exclude-module", "PySide6.QtQuick",
        "--exclude-module", "PySide6.QtQuickWidgets",
        "--exclude-module", "PySide6.QtWebEngineCore",
        "--exclude-module", "PySide6.QtWebEngineWidgets",
        "--exclude-module", "PySide6.Qt3DCore",
        "--exclude-module", "tkinter",
        *icon_args,
        *add_binary_args,
        str(entry),
    ]
    print("RUN:", " ".join(cmd))
    rc = subprocess.call(cmd, cwd=str(ROOT))
    if rc != 0:
        return rc

    app_dir = DIST_WORK / "ThroughFocus_Viewer"
    if not app_dir.is_dir():
        print(f"[ERROR] dist missing: {app_dir}")
        return 1

    if OUT_ROOT.exists():
        shutil.rmtree(OUT_ROOT, ignore_errors=True)
    OUT_ROOT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(app_dir, OUT_ROOT)

    copied = _copy_extra_dlls(OUT_ROOT)
    print("[OK] extra DLLs:", ", ".join(copied) or "(none found)")

    help_src = ROOT / "ThroughFocus_Viewer_Help.html"
    if help_src.is_file():
        shutil.copy2(help_src, OUT_ROOT / "ThroughFocus_Viewer_Help.html")

    # Runtime window icon next to exe / 執行期視窗圖示（與 exe 同層 assets）
    assets_src = ROOT / "assets"
    if assets_src.is_dir():
        assets_dst = OUT_ROOT / "assets"
        if assets_dst.exists():
            shutil.rmtree(assets_dst, ignore_errors=True)
        shutil.copytree(assets_src, assets_dst)

    (OUT_ROOT / "run_ThroughFocus_Viewer.bat").write_text(
        "@echo off\r\ncd /d \"%~dp0\"\r\nstart \"\" \"%~dp0ThroughFocus_Viewer.exe\" %*\r\n",
        encoding="ascii", newline="\r\n",
    )
    (OUT_ROOT / "STANDALONE_README.txt").write_text(
        f"ThroughFocus_Viewer v{__version__} — Windows standalone\r\n"
        "====================================================\r\n\r\n"
        "No Python install required / 不需安裝 Python。\r\n\r\n"
        "Run: run_ThroughFocus_Viewer.bat  or  ThroughFocus_Viewer.exe\r\n\r\n"
        "If DLL errors occur on a clean PC, install Microsoft Visual C++\r\n"
        "Redistributable (x64) from Microsoft.\r\n"
        "若出現 DLL 錯誤，請安裝 Microsoft Visual C++ Redistributable (x64)。\r\n\r\n"
        "Optional Sample\\ folder next to the exe opens as default Group.\r\n"
        "可選：exe 旁 Sample\\ 作為無參數預設圖集。\r\n\r\n"
        "Help: ThroughFocus_Viewer_Help.html (F1)\r\n",
        encoding="utf-8", newline="\r\n",
    )

    total = sum(p.stat().st_size for p in OUT_ROOT.rglob("*") if p.is_file())
    print(f"[OK] {OUT_ROOT}")
    print(f"[OK] size ≈ {total / (1024 * 1024):.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())