"""Safe path strings for UI / log (no home-directory PII).

UI／日誌用安全路徑（不含使用者家目錄個資）。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Match C:\Users\name\... and C:/Users/name/... /
# 同時匹配反斜線與正斜線家目錄路徑
_RE_WIN_USER = re.compile(
    r"(?i)[A-Z]:[\\/]+Users[\\/]+[^\\/\s\"'<>|]+(?:[\\/]+[^\s\"'<>|]*)*")
_RE_UNIX_HOME = re.compile(
    r"(?i)(?:(?<![A-Za-z:])/home|/Users)/[^/\s\"'<>|]+(?:/[^\s\"'<>|]*)*")


def safe_display_path(path: str | os.PathLike[str], *, parents: int = 1) -> str:
    """Return parent/name (or basename) for UI / log display."""
    raw = str(path).strip().strip('"')
    if not raw:
        return raw
    # Normalize slashes for Path parsing on Windows /
    # Windows 上統一斜線方便 Path 解析
    norm = raw.replace("/", "\\") if (len(raw) >= 2 and raw[1] == ":") else raw
    p = Path(norm)
    parts = p.parts
    start = 0
    if len(parts) >= 1 and (parts[0].endswith(":") or parts[0] in ("/", "\\")):
        start = 1
    if len(parts) >= start + 2 and parts[start].lower() in ("users", "home"):
        start += 2
    elif len(parts) >= start + 1 and parts[start] == "Documents":
        start += 1
    useful = parts[start:] if start < len(parts) else parts
    if not useful:
        useful = (p.name,) if p.name else parts[-1:]
    n = max(1, int(parents) + 1)
    tail = useful[-n:] if len(useful) >= n else useful
    return "/".join(tail)


def redact_paths_in_text(text: str, *, parents: int = 1) -> str:
    """Replace absolute user-home paths in free text with a short tail."""
    if not text:
        return text

    def _tail(full: str) -> str:
        return safe_display_path(full, parents=parents)

    out = _RE_WIN_USER.sub(lambda m: _tail(m.group(0)), text)
    out = _RE_UNIX_HOME.sub(lambda m: _tail(m.group(0)), out)
    return out