"""UI language (EN / 中文) for Viewer display strings.

Viewer 介面語言（英文／中文）顯示字串。
"""

from __future__ import annotations

from typing import Dict

LANG_EN = "en"
LANG_ZH = "zh"
LANG_MODES = (LANG_EN, LANG_ZH)

# Combo display labels / 下拉顯示名稱
LANG_LABELS = {
    LANG_EN: "English",
    LANG_ZH: "中文",
}

_STRINGS: Dict[str, Dict[str, str]] = {
    LANG_EN: {
        "focus_axis": "Focus [{unit}]",
        "radial_axis": "Radial axis [{unit}]",
        "aspect_fill": "Fixed Window",
        "aspect_physical": "Physical",
        "aspect_fill_cap": "Aspect=Fixed Window",
        "aspect_physical_cap": "Aspect=Physical",
        "aspect_clamped": "clamped",
        "axes_on": "Axes=on",
        "axes_off": "Axes=off",
        "unit_label": "Unit",
        "lang_label": "Lang",
        "peak_norm": "peak-norm max=1",
        "raw_intensity": "raw intensity",
        "intensity_short": "I",
        "intensity_scale": "Intensity",
    },
    LANG_ZH: {
        "focus_axis": "焦點 [{unit}]",
        "radial_axis": "徑向軸 [{unit}]",
        "aspect_fill": "固定視窗",
        "aspect_physical": "實際比例",
        "aspect_fill_cap": "Aspect=固定視窗",
        "aspect_physical_cap": "Aspect=實際比例",
        "aspect_clamped": "已夾限",
        "axes_on": "Axes=開",
        "axes_off": "Axes=關",
        "unit_label": "單位",
        "lang_label": "語言",
        "peak_norm": "峰值歸一 max=1",
        "raw_intensity": "原始強度",
        "intensity_short": "I",
        "intensity_scale": "強度",
    },
}


def normalize_lang(lang: str) -> str:
    """Return LANG_EN or LANG_ZH / 回傳 en 或 zh。"""
    if lang in (LANG_ZH, "zh-TW", "zh_CN", "中文", "Chinese"):
        return LANG_ZH
    return LANG_EN


def tr(lang: str, key: str, **kwargs: str) -> str:
    """Translate ``key`` for ``lang`` with optional format kwargs.

    依語言翻譯 ``key``；可帶 format 參數。
    """
    lang = normalize_lang(lang)
    table = _STRINGS.get(lang) or _STRINGS[LANG_EN]
    text = table.get(key) or _STRINGS[LANG_EN].get(key) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text
    return text
