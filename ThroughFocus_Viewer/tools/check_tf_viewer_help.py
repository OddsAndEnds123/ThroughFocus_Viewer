"""Scan public Help / launchers / optional source for banned keywords.

檢查公開 Help、啟動 bat，以及（可選）全部 viewer 程式碼的禁用關鍵字。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Monitored banned keywords / 監察中的禁用關鍵字
BANNED_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Zemax", re.compile(r"zemax", re.I)),
    ("OpticStudio", re.compile(r"optic\s*studio|opticstudio", re.I)),
    ("ZPL", re.compile(r"\bZPL\b")),
    ("Zernike", re.compile(r"zernike", re.I)),
    ("Nijboer", re.compile(r"nijboer", re.I)),
    ("TF_GBM", re.compile(r"TF[_\-]?GBM", re.I)),
    ("ENZ", re.compile(r"\bENZ\b")),
    ("ENZ_Viewer", re.compile(r"\\bENZ[_\\s\\-]Viewer\\b", re.I)),
    ("ENZViewer", re.compile(r"ENZViewer", re.I)),
    ("enz-wavefront", re.compile(r"enz-wavefront", re.I)),
    ("enz_window", re.compile(r"enz_window", re.I)),
    ("EnzWindow", re.compile(r"EnzWindow")),
    ("run_enz_viewer", re.compile(r"run_enz_viewer", re.I)),
    ("Sample folder path", re.compile(
        r"(?:^|[^A-Za-z0-9_])Sample(?:/|\\)|/Sample/|\\Sample\\")),
    ("Embedded image", re.compile(r"<img\b|data:image/", re.I)),
]

PUBLIC_TARGETS = [
    "ThroughFocus_Viewer_Help.html",
    "run_throughfocus_viewer.bat",
]

CODE_GLOBS = [
    "src/viewer/**/*.py",
]


def scan_text(path: Path, text: str) -> list[str]:
    hits: list[str] = []
    lines = text.splitlines()
    for label, pat in BANNED_PATTERNS:
        for i, line in enumerate(lines, 1):
            if pat.search(line):
                snippet = line.strip()
                if len(snippet) > 120:
                    snippet = snippet[:117] + "..."
                hits.append(f"{path.as_posix()}:{i}: [{label}] {snippet}")
    return hits


def iter_code_files(base: Path) -> list[Path]:
    files: list[Path] = []
    for pattern in CODE_GLOBS:
        files.extend(base.glob(pattern))
    return sorted({p.resolve() for p in files if p.is_file()})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Monitor banned keywords in TF Viewer public files "
            "and optionally all viewer source / 監察禁用關鍵字"))
    parser.add_argument(
        "paths", nargs="*", type=Path,
        help="Extra files to treat as public (must be clean)")
    parser.add_argument(
        "--code", action="store_true",
        help="Also scan all viewer *.py (report CODE hits; exit 0 if public clean)")
    parser.add_argument(
        "--strict-code", action="store_true",
        help="With --code: CODE hits also fail (exit 1)")
    parser.add_argument(
        "--list-keywords", action="store_true",
        help="Print monitored keyword labels and exit")
    args = parser.parse_args(argv)

    if args.list_keywords:
        print("Monitored keywords / 監察關鍵字:")
        for label, _ in BANNED_PATTERNS:
            print(f"  - {label}")
        return 0

    base = Path(__file__).resolve().parent.parent
    public_paths = [base / name for name in PUBLIC_TARGETS] + list(args.paths)

    public_hits: list[str] = []
    print("=== PUBLIC (must be clean) / 公開檔（必須乾淨）===")
    for path in public_paths:
        path = path.resolve()
        if not path.is_file():
            print(f"[MISS] {path}")
            public_hits.append(f"missing:{path}")
            continue
        # bat may be cp950; try utf-8 then latin-1
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="latin-1")
        hits = scan_text(path, text)
        if hits:
            print(f"[FAIL] {path.relative_to(base)}: {len(hits)} hit(s)")
            for h in hits:
                print(" ", h)
            public_hits.extend(hits)
        else:
            print(f"[PASS] {path.relative_to(base)}")

    code_hits: list[str] = []
    if args.code or args.strict_code:
        print()
        print("=== CODE (monitor) / 程式碼（監察）===")
        for path in iter_code_files(base):
            text = path.read_text(encoding="utf-8")
            hits = scan_text(path, text)
            rel = path.relative_to(base)
            if hits:
                print(f"[CODE] {rel}: {len(hits)} hit(s)")
                for h in hits[:20]:
                    print(" ", h)
                if len(hits) > 20:
                    print(f"  ... +{len(hits) - 20} more")
                code_hits.extend(hits)
            else:
                print(f"[PASS] {rel}")

    print()
    print("Keywords monitored / 已監察關鍵字數:", len(BANNED_PATTERNS))
    if public_hits:
        print(f"RESULT: FAIL public ({len(public_hits)} issue(s))")
        return 1
    if (args.strict_code) and code_hits:
        print(f"RESULT: FAIL code ({len(code_hits)} issue(s))")
        return 1
    if code_hits:
        print(f"RESULT: PASS public; CODE has {len(code_hits)} monitored hit(s)")
        return 0
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
