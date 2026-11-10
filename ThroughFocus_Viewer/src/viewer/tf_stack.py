"""Through-focus stack parsing and grouping.

通焦疊圖解析與分組。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

# Example: ..._step01of21_dz+10.0mm_..._Field1.bmp
_TF_RE = re.compile(
    r"step(?P<step>\d+)of(?P<total>\d+)_dz(?P<dz>[+-]?\d+(?:\.\d+)?)mm",
    re.IGNORECASE,
)
_FIELD_RE = re.compile(r"Field(?P<field>\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class TfMeta:
    """Metadata parsed from a through-focus filename / 從通焦檔名解析的中繼資料。"""

    step: int
    total: int
    dz_mm: float
    field: Optional[str]
    group_key: str


def parse_tf_meta(path: str) -> Optional[TfMeta]:
    """Parses step/dz/field from a path, or None if not a TF frame.

    從路徑解析步階／dz／Field；非通焦影格則回傳 None。
    """
    name = os.path.basename(path)
    m = _TF_RE.search(name)
    if m is None:
        return None
    step = int(m.group("step"))
    total = int(m.group("total"))
    dz_mm = float(m.group("dz"))
    field: Optional[str] = None
    fm = _FIELD_RE.search(name)
    if fm is not None:
        field = f"Field{fm.group('field')}"
    else:
        parent = os.path.basename(os.path.dirname(os.path.abspath(path)))
        pm = _FIELD_RE.search(parent)
        if pm is not None:
            field = f"Field{pm.group('field')}"
    if field is not None:
        group_key = field
    else:
        # Same run stem without step/dz / 去掉步階與 dz 後的同批前綴
        stem = _TF_RE.sub("tfstack", name, count=1)
        group_key = os.path.splitext(stem)[0]
    return TfMeta(step=step, total=total, dz_mm=dz_mm, field=field,
                  group_key=group_key)


def format_dz(dz_mm: float) -> str:
    """Formats dz for UI labels / 格式化 dz 供介面標籤。"""
    return f"dz{dz_mm:+.1f}mm"


def group_paths_into_stacks(
    paths: Sequence[str],
) -> List[Tuple[str, List[str], List[Optional[TfMeta]]]]:
    """Groups image paths into through-focus stacks (or singleton stacks).

    Through-focus frames with the same Field/group_key become one stack, sorted
    by step then dz. Non-TF images each form a one-frame stack.

    將影像路徑分成通焦疊圖（或單張疊）。同一 Field／group_key 的通焦
    影格合成一疊，依 step、dz 排序；非 TF 影像各成單張疊。

    Returns:
        list of (label, paths, metas) / （標籤、路徑清單、中繼資料清單）。
    """
    tf_groups: Dict[str, List[Tuple[str, TfMeta]]] = {}
    order: List[str] = []
    singles: List[Tuple[str, List[str], List[Optional[TfMeta]]]] = []

    for path in paths:
        meta = parse_tf_meta(path)
        if meta is None:
            label = os.path.basename(path)
            singles.append((label, [path], [None]))
            continue
        key = meta.group_key
        if key not in tf_groups:
            tf_groups[key] = []
            order.append(key)
        tf_groups[key].append((path, meta))

    stacks: List[Tuple[str, List[str], List[Optional[TfMeta]]]] = []
    for key in order:
        items = sorted(tf_groups[key], key=lambda t: (t[1].step, t[1].dz_mm))
        paths_g = [p for p, _ in items]
        metas_g: List[Optional[TfMeta]] = [m for _, m in items]
        stacks.append((key, paths_g, metas_g))
    stacks.extend(singles)
    return stacks


def folder_as_stack(
    folder: str, paths: Sequence[str],
) -> Tuple[str, List[str], List[Optional[TfMeta]]]:
    """One Frames group for an entire folder (label = folder name).

    整個資料夾合成 Frames 的一個 group（標籤為資料夾名稱）。
    TF metas are still parsed for step/dz labels when filenames match.
    檔名符合時仍解析 TF meta，供步階／dz 標籤使用。
    """
    label = os.path.basename(os.path.abspath(folder.rstrip("\\/"))) or folder
    metas: List[Optional[TfMeta]] = [parse_tf_meta(p) for p in paths]
    if metas and all(m is not None for m in metas):
        paired = sorted(zip(paths, metas), key=lambda t: (t[1].step, t[1].dz_mm))
        paths_out = [pp for pp, _ in paired]
        metas_out = [m for _, m in paired]
    else:
        paths_out = list(paths)
        metas_out = metas
    return label, paths_out, metas_out
