"""Align ROI centre to in-focus image intensity centroid.

將 ROI 中心對齊到合焦影像的強度質心。
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import numpy as np

from viewer.roi import RotatedRoi
from viewer.tf_stack import TfMeta


def best_focus_index(metas: Sequence[Optional[TfMeta]], n_frames: int) -> int:
    """Index of the in-focus frame (dz closest to 0, else mid).

    合焦幀索引：dz 最接近 0；無 meta 則取中間步。
    """
    n = max(int(n_frames), 1)
    if metas and len(metas) == n and all(m is not None for m in metas):
        dz = np.array([float(m.dz_mm) for m in metas], dtype=np.float64)  # type: ignore[union-attr]
        return int(np.argmin(np.abs(dz)))
    return (n - 1) // 2


def roi_intensity_centroid(
    luminance: np.ndarray,
    roi: RotatedRoi,
    *,
    thresh_frac: float = 0.2,
) -> Optional[Tuple[float, float]]:
    """Intensity-weighted centroid inside the ROI (image px).

    ROI 內強度加權質心（影像像素座標）。Returns None if no usable mass.
    """
    if luminance.ndim != 2:
        raise ValueError("luminance must be 2-D / 亮度須為二維")
    h, w = luminance.shape
    bx, by, bw, bh = roi.bbox()
    x0 = max(int(np.floor(bx)) - 1, 0)
    y0 = max(int(np.floor(by)) - 1, 0)
    x1 = min(int(np.ceil(bx + bw)) + 2, w)
    y1 = min(int(np.ceil(by + bh)) + 2, h)
    if x1 <= x0 or y1 <= y0:
        return None
    yy, xx = np.mgrid[y0:y1, x0:x1]
    # Pixel centres at integer coords / 像素中心在整數座標
    xs = xx.astype(np.float64)
    ys = yy.astype(np.float64)
    mask = roi.contains(xs, ys)
    if not np.any(mask):
        return None
    vals = luminance[y0:y1, x0:x1].astype(np.float64)
    sub = vals[mask]
    peak = float(np.nanmax(sub))
    if not np.isfinite(peak) or peak <= 0:
        return None
    floor = peak * float(thresh_frac)
    weights = np.clip(sub - floor, 0.0, None)
    mass = float(np.sum(weights))
    if mass <= 1e-12:
        # Fall back to unthresholded mass / 退回未門檻質量
        weights = np.clip(sub, 0.0, None)
        mass = float(np.sum(weights))
        if mass <= 1e-12:
            return None
    cx = float(np.sum(xs[mask] * weights) / mass)
    cy = float(np.sum(ys[mask] * weights) / mass)
    return cx, cy


def snap_roi_to_focus_centroid(
    frames_luminance: Sequence[np.ndarray],
    metas: Sequence[Optional[TfMeta]],
    roi: RotatedRoi,
) -> Tuple[bool, int, Optional[Tuple[float, float]]]:
    """Move ``roi.cx/cy`` to centroid on the best-focus frame.

    在合焦幀上將 ``roi.cx/cy`` 移到質心。

    Returns:
        (moved, focus_index, (cx, cy) or None)
    """
    if not frames_luminance:
        return False, 0, None
    fi = best_focus_index(list(metas), len(frames_luminance))
    lum = frames_luminance[fi]
    cen = roi_intensity_centroid(lum, roi)
    if cen is None:
        return False, fi, None
    ncx, ncy = cen
    moved = abs(ncx - roi.cx) > 1e-6 or abs(ncy - roi.cy) > 1e-6
    roi.cx = ncx
    roi.cy = ncy
    return moved, fi, cen
