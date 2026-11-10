"""Through-focus intensity map from a Group stack + ROI (Fig.2-style).

由 Group 通焦疊圖與 ROI 建立通焦強度圖（仿 Fig.2 Focus×Radial）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np

from viewer.image_io import LoadedImage
from viewer.profile import ProfileSettings, extract_profile
from viewer.roi import RotatedRoi
from viewer.tf_stack import TfMeta


# Unit labels on the UI / 畫面上的單位標籤
UNIT_UM = "µm"
UNIT_NM = "nm"
SCALE_UNITS = (UNIT_UM, UNIT_NM)

# Manual NA: NULL or [1e-8, 2.0] / 手填 NA：NULL 或 [1e-8, 2.0]
NA_NULL_SENTINEL = 0.0  # spin minimum → shows "NULL"
NA_MIN = 1e-8
NA_MAX = 2.0

# Manual Wavenumber: NULL or [1e-8, 1e6] (metadata; not Unit-scaled) /
# 手填 Wavenumber：NULL 或 [1e-8, 1e6]（記錄用；不隨 Unit 換算）
WN_NULL_SENTINEL = 0.0
WN_MIN = 1e-8
WN_MAX = 1e6


def format_na(na: Optional[float]) -> str:
    """Excel / Info text for NA / NA 的匯出字串。"""
    if na is None:
        return "NULL"
    return f"{float(na):.8g}"


def format_wavenumber(wavenumber: Optional[float]) -> str:
    """Excel / Info text for Wavenumber / Wavenumber 匯出字串。"""
    if wavenumber is None:
        return "NULL"
    return f"{float(wavenumber):.8g}"


def normalize_na(value: Optional[float]) -> Optional[float]:
    """None/≤0 → NULL; else clamp to [NA_MIN, NA_MAX].

    None／≤0 → NULL；否則夾到 [NA_MIN, NA_MAX]。
    """
    if value is None:
        return None
    v = float(value)
    if not math.isfinite(v) or v <= NA_NULL_SENTINEL:
        return None
    if v < NA_MIN:
        return NA_MIN
    if v > NA_MAX:
        return NA_MAX
    return v


def normalize_wavenumber(value: Optional[float]) -> Optional[float]:
    """None/≤0 → NULL; else clamp to [WN_MIN, WN_MAX].

    None／≤0 → NULL；否則夾到 [WN_MIN, WN_MAX]。
    """
    if value is None:
        return None
    v = float(value)
    if not math.isfinite(v) or v <= WN_NULL_SENTINEL:
        return None
    if v < WN_MIN:
        return WN_MIN
    if v > WN_MAX:
        return WN_MAX
    return v


def unit_to_um_factor(unit: str) -> float:
    """Multiply displayed value by this to get micrometres / 顯示值×此係數＝µm。"""
    if unit == UNIT_NM:
        return 1e-3
    if unit == UNIT_UM:
        return 1.0
    raise ValueError(f"Unknown unit {unit!r} / 未知單位")


def um_to_unit_factor(unit: str) -> float:
    """Multiply micrometres by this to get display unit / µm×此係數＝顯示單位。"""
    return 1.0 / unit_to_um_factor(unit)


@dataclass
class ScaleSettings:
    """Physical scale with one shared unit / 共用同一單位的物理尺度。"""

    x_pixel: float = 1.0
    y_pixel: float = 1.0
    z_step: float = 1.0
    # None = NULL (unset); else in [WN_MIN, WN_MAX]
    # None＝未填；否則落在 [WN_MIN, WN_MAX]
    wavenumber: Optional[float] = None
    unit: str = UNIT_UM
    # None = NULL (unset); else in [NA_MIN, NA_MAX]
    # None＝未填；否則落在 [NA_MIN, NA_MAX]
    na: Optional[float] = None

    def validate(self) -> None:
        if self.unit not in SCALE_UNITS:
            raise ValueError(f"unit must be µm or nm / 單位須為 µm 或 nm")
        if self.x_pixel <= 0 or self.y_pixel <= 0 or self.z_step <= 0:
            raise ValueError("sizes must be positive / 尺度必須為正數")
        if self.wavenumber is not None:
            if self.wavenumber < WN_MIN or self.wavenumber > WN_MAX:
                raise ValueError(
                    f"Wavenumber must be NULL or in [{WN_MIN:g}, {WN_MAX:g}] / "
                    f"Wavenumber 須為 NULL 或介於 [{WN_MIN:g}, {WN_MAX:g}]")
        if self.na is not None:
            if self.na < NA_MIN or self.na > NA_MAX:
                raise ValueError(
                    f"NA must be NULL or in [{NA_MIN:g}, {NA_MAX:g}] / "
                    f"NA 須為 NULL 或介於 [{NA_MIN:g}, {NA_MAX:g}]")

@dataclass
class ThroughFocusMap:
    """2-D intensity I(radial, focus) for contouring / 供等高線的 2-D 強度。"""

    radial: np.ndarray  # 1-D, display unit (physical)
    focus: np.ndarray  # 1-D, display unit (physical)
    intensity: np.ndarray  # shape (n_focus, n_radial)
    unit: str
    roi_id: int
    n_frames: int
    normalized: bool = True  # peak-norm if True / True＝峰值歸一


def _radial_px_to_unit(pos_px: np.ndarray, roi: RotatedRoi,
                      scale: ScaleSettings) -> np.ndarray:
    """Converts profile positions (px along u) to physical radial axis.

    將剖面位置（沿 u 的像素）轉成物理徑向座標。
    """
    th = roi.angle_rad
    # One pixel step along u in image (x,y) / 沿 u 一像素在影像座標的步長
    ux, uy = math.cos(th), -math.sin(th)
    step = math.hypot(ux * scale.x_pixel, uy * scale.y_pixel)
    return np.asarray(pos_px, dtype=np.float64) * step


def _focus_axis_from_metas(
    metas: Sequence[Optional[TfMeta]],
    n: int,
    scale: ScaleSettings,
) -> np.ndarray:
    """Focus coordinates in display unit / 顯示單位的焦點座標。"""
    to_disp = um_to_unit_factor(scale.unit)
    # Prefer filename dz (mm → µm → display) / 優先檔名 dz（mm→µm→顯示）
    if metas and len(metas) == n and all(m is not None for m in metas):
        z_um = np.array([m.dz_mm * 1e3 for m in metas], dtype=np.float64)
        return z_um * to_disp
    # Manual Z step, centred on mid index / 手動 Z step，以中間索引為 0
    mid = (n - 1) / 2.0
    return (np.arange(n, dtype=np.float64) - mid) * scale.z_step


def build_through_focus_map(
    frames: Sequence[LoadedImage],
    metas: Sequence[Optional[TfMeta]],
    roi: RotatedRoi,
    scale: ScaleSettings,
    profile_settings: Optional[ProfileSettings] = None,
    *,
    normalize: bool = True,
) -> ThroughFocusMap:
    """Builds I(focus, radial) in physical units; optional peak-norm.

    建立實際尺寸的 I(focus, radial)；可選峰值歸一。
    """
    scale.validate()
    if not frames:
        raise ValueError("No frames / 沒有影格")
    cfg = profile_settings or ProfileSettings(method="bilinear", step=0.5)
    rows: List[np.ndarray] = []
    radial_ref: Optional[np.ndarray] = None
    for img in frames:
        prof = extract_profile(img.luminance, roi, cfg)
        rad = _radial_px_to_unit(prof.position, roi, scale)
        inten = np.asarray(prof.intensity, dtype=np.float64)
        if radial_ref is None:
            radial_ref = np.asarray(rad, dtype=np.float64)
            rows.append(inten)
        elif (rad.shape == radial_ref.shape
              and np.allclose(rad, radial_ref, rtol=0.0, atol=1e-9)):
            # Same grid: keep NaNs (out-of-image samples) /
            # 同格點：保留 NaN（超出影像的取樣）
            rows.append(inten)
        else:
            # Nearest finite only — do not fill gaps across NaN /
            # 僅對齊最近有限值，不以內插填補 NaN 缺口
            row = np.full(radial_ref.shape, np.nan, dtype=np.float64)
            ok = np.isfinite(inten) & np.isfinite(rad)
            if ok.any():
                idx = np.abs(
                    radial_ref[:, None] - rad[ok][None, :]).argmin(axis=1)
                src = rad[ok]
                step = (float(np.median(np.diff(src)))
                        if src.size > 1 else 0.0)
                tol = max(abs(step) * 0.51, 1e-9)
                dist = np.abs(radial_ref - src[idx])
                near = dist <= tol
                row[near] = inten[ok][idx[near]]
            rows.append(row)
    intensity = np.vstack(rows)
    # Keep out-of-image NaNs (do not invent edge values) /
    # 保留超出影像的 NaN（不以邊緣值填補）
    did_norm = False
    if normalize:
        peak = float(np.nanmax(intensity)) if intensity.size else 0.0
        if np.isfinite(peak) and peak > 0:
            intensity = intensity / peak
            did_norm = True
    focus = _focus_axis_from_metas(metas, len(frames), scale)
    return ThroughFocusMap(
        radial=radial_ref,
        focus=focus,
        intensity=intensity,
        unit=scale.unit,
        roi_id=roi.roi_id,
        n_frames=len(frames),
        normalized=did_norm,
    )


# Contour levels similar to Fig.2 / 近似 Fig.2 的等高線層級
DEFAULT_LEVELS: Tuple[float, ...] = (
    0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9)
