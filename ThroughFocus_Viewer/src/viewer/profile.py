"""Line profile (LSF) extraction and summary metrics.

Line Profile（LSF）擷取與摘要指標。

Definitions follow the reference paper "Comparison of MTF measurements using
edge method: towards reference data set" (Viallefont-Robinet et al., Optics
Express 26(26), 2018), adapted from edges to line targets:
定義參考論文（Viallefont-Robinet 等，Optics Express 2018），由邊緣改為線目標：

* Kohm / CSIR approach (Sec. 2.2.2, Fig. 2, Eq. 9): the ROI is a rectangle
  aligned with the feature, and every sample is projected on the unit normal
  ``n`` of the feature: ``z = n · (p - p0)``. Here ``n`` is the ROI u-axis and
  ``p0`` the ROI centre, so the profile position is ``z`` (px).
  ROI 與特徵對齊，每個取樣點投影到特徵的法向量 n：z = n·(p − p0)。
  此處 n 為 ROI 的 u 軸、p0 為 ROI 中心，剖面位置即 z（像素）。
* Uniform resampling by binning (Sec. 2.2.2, ISO 12233-inspired) with
  spacing ``step`` (default 1/4 px), method ``project``.
  以均勻 bin（預設 1/4 像素）重新取樣，即 ``project`` 方法。
* ``bilinear`` / ``bicubic`` methods: sample the image on the rotated ROI
  grid by interpolation and average along the line (v) direction.
  ``bilinear`` / ``bicubic``：在旋轉 ROI 網格上內插取樣，沿線方向（v）平均。
* SNR (Sec. 3.2, SDSU): feature height divided by the average of the standard
  deviations of the regions on either side of the feature.
  SNR（3.2 節）：特徵高度除以兩側區域標準差的平均。

FWHM / LSF widths are intentionally NOT computed in v0.1 (user request).
依使用者要求，v0.1 刻意不計算 FWHM / LSF 寬度。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import warnings
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy import ndimage

from viewer.roi import RotatedRoi

# Sampling methods / 取樣方法
METHODS = ("bilinear", "bicubic", "project")


@dataclass
class ProfileSettings:
    """Line-profile settings / Line Profile 設定。

    Attributes:
        method: "bilinear" (default), "bicubic" or "project" (Kohm binning).
            取樣方法：bilinear（預設）、bicubic 或 project（Kohm 投影分箱）。
        step: Spacing of profile positions along u (px) / 剖面取樣間距（像素）。
        along_step: Spacing of averaged samples along v (px, interpolation
            methods only) / 沿線方向平均的取樣間距（像素，僅內插方法）。
        tail_fraction: Fraction of dx at EACH end used for background/noise.
            兩端各取 dx 的比例作為背景／雜訊區。
        signal_threshold: Fraction of peak height bounding the centroid/area
            region / 質心與面積計算區域的峰值比例門檻。
    """

    method: str = "bilinear"
    step: float = 0.25
    along_step: float = 1.0
    tail_fraction: float = 0.2
    signal_threshold: float = 0.05

    def validate(self) -> None:
        """Validates settings / 驗證設定。

        Raises:
            ValueError: Invalid setting / 設定無效。
        """
        if self.method not in METHODS:
            raise ValueError(
                f"Unknown method '{self.method}' / 未知方法 '{self.method}'")
        if not 0 < self.step <= 5:
            raise ValueError("step must be in (0, 5] px / step 須介於 (0, 5]")
        if not 0 < self.along_step <= 10:
            raise ValueError(
                "along_step must be in (0, 10] px / along_step 須介於 (0, 10]")
        if not 0.05 <= self.tail_fraction <= 0.45:
            raise ValueError(
                "tail_fraction must be in [0.05, 0.45] / tail_fraction 須介於 "
                "[0.05, 0.45]")


@dataclass
class LineProfile:
    """Extracted line profile and metrics / 擷取的 Line Profile 與指標。

    Attributes:
        roi: Source ROI / 來源 ROI。
        position: Profile positions z along u relative to the ROI centre (px).
            相對 ROI 中心沿 u 的位置 z（像素）。
        intensity: Mean intensity at each position (code values).
            各位置的平均強度（原始數值）。
        intensity_std: Std of the averaged samples at each position.
            各位置被平均樣本的標準差。
        count: Number of samples averaged at each position / 各位置樣本數。
        sample_x: Image x of each position on the ROI centre line / 中心線 x。
        sample_y: Image y of each position on the ROI centre line / 中心線 y。
        metrics: Summary metrics (see ``METRIC_KEYS``) / 摘要指標。
        settings: Settings used / 使用的設定。
    """

    roi: RotatedRoi
    position: np.ndarray
    intensity: np.ndarray
    intensity_std: np.ndarray
    count: np.ndarray
    sample_x: np.ndarray
    sample_y: np.ndarray
    metrics: Dict[str, float] = field(default_factory=dict)
    settings: ProfileSettings = field(default_factory=ProfileSettings)

    @property
    def normalized(self) -> np.ndarray:
        """Background-subtracted, polarity-corrected, peak-normalised profile.

        扣除背景、極性校正並以峰值正規化的剖面（峰值 = 1）。
        """
        bg = self.metrics.get("Background", 0.0)
        height = self.metrics.get("Peak_Height", 0.0)
        sign = 1.0 if self.metrics.get("Polarity_Sign", 1.0) >= 0 else -1.0
        if height == 0 or not math.isfinite(height):
            return np.zeros_like(self.intensity)
        return sign * (self.intensity - bg) / height


# Ordered metric names shown in the Result panel / CSV.
# Result 面板與 CSV 中的指標順序。
METRIC_KEYS: List[str] = [
    "Polarity",
    "Background",
    "Background_Std",
    "Peak_Value",
    "Peak_Height",
    "Peak_Pos_px",
    "Peak_X",
    "Peak_Y",
    "Centroid_px",
    "Centroid_X",
    "Centroid_Y",
    "Area",
    "SNR",
]


def _sample_interpolated(
    image: np.ndarray, roi: RotatedRoi, settings: ProfileSettings
) -> tuple:
    """Interpolates the image on the rotated ROI grid.

    在旋轉 ROI 網格上內插取樣影像。

    Args:
        image: H×W float image / 影像。
        roi: ROI / ROI。
        settings: Settings / 設定。

    Returns:
        tuple: (positions, mean, std, count) / (位置, 平均, 標準差, 樣本數)。
    """
    half_s, half_t = roi.dx / 2.0, roi.dy / 2.0
    s = np.arange(-half_s, half_s + 1e-9, settings.step)
    n_t = max(1, int(math.floor(roi.dy / settings.along_step)) + 1)
    t = (np.linspace(-half_t, half_t, n_t) if n_t > 1 else np.array([0.0]))
    ss, tt = np.meshgrid(s, t)  # rows: t, cols: s / 列為 t、行為 s
    xs, ys = roi.local_to_image(ss, tt)
    order = 1 if settings.method == "bilinear" else 3
    values = ndimage.map_coordinates(
        image, [ys.ravel(), xs.ravel()], order=order, mode="nearest",
        prefilter=(order > 1)).reshape(ss.shape)
    h, w = image.shape
    inside = (xs >= -0.5) & (xs <= w - 0.5) & (ys >= -0.5) & (ys <= h - 0.5)
    values = np.where(inside, values, np.nan)
    count = np.sum(inside, axis=0)
    with np.errstate(invalid="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        mean = np.nanmean(values, axis=0)
        std = np.nanstd(values, axis=0)
    return s, mean, std, count


def _sample_projected(
    image: np.ndarray, roi: RotatedRoi, settings: ProfileSettings
) -> tuple:
    """Kohm projection binning (paper Eq. 9) of pixel centres inside the ROI.

    將 ROI 內像素中心以 Kohm 投影（論文式 9）分箱。

    Args:
        image: H×W float image / 影像。
        roi: ROI / ROI。
        settings: Settings / 設定。

    Returns:
        tuple: (positions, mean, std, count) / (位置, 平均, 標準差, 樣本數)。
    """
    h, w = image.shape
    corners = np.array(roi.corners())
    x0 = max(0, int(math.floor(corners[:, 0].min())))
    x1 = min(w - 1, int(math.ceil(corners[:, 0].max())))
    y0 = max(0, int(math.floor(corners[:, 1].min())))
    y1 = min(h - 1, int(math.ceil(corners[:, 1].max())))
    half_s = roi.dx / 2.0
    s_grid = np.arange(-half_s, half_s + 1e-9, settings.step)
    if x1 < x0 or y1 < y0:
        nan = np.full_like(s_grid, np.nan)
        return s_grid, nan, nan.copy(), np.zeros_like(s_grid, dtype=int)
    yy, xx = np.mgrid[y0:y1 + 1, x0:x1 + 1]
    mask = roi.contains(xx, yy)
    ux, uy = roi.u_axis
    z = (xx[mask] - roi.cx) * ux + (yy[mask] - roi.cy) * uy  # Eq. (9)
    vals = image[yy[mask], xx[mask]]
    idx = np.rint((z + half_s) / settings.step).astype(int)
    valid = (idx >= 0) & (idx < s_grid.size)
    idx, vals = idx[valid], vals[valid]
    count = np.bincount(idx, minlength=s_grid.size)
    total = np.bincount(idx, weights=vals, minlength=s_grid.size)
    total_sq = np.bincount(idx, weights=vals * vals, minlength=s_grid.size)
    # Empty bins stay NaN (no inventing out-of-image samples) /
    # 空 bin 維持 NaN（不為超出影像的位置捏造數值）
    mean = np.full(s_grid.size, np.nan, dtype=np.float64)
    std = np.full(s_grid.size, np.nan, dtype=np.float64)
    with np.errstate(invalid="ignore", divide="ignore"):
        ok = count > 0
        mean[ok] = total[ok] / count[ok]
        std[ok] = np.sqrt(
            np.maximum(total_sq[ok] / count[ok] - mean[ok] * mean[ok], 0.0))
    return s_grid, mean, std, count


def _parabolic_peak(z: np.ndarray, y: np.ndarray, i: int) -> float:
    """Sub-sample peak position by a least-squares parabola.

    以最小平方拋物線估計次取樣峰值位置。

    The parabola is fitted to the contiguous samples around the maximum that
    are above 50 % of it (robust to the piecewise-linear shape produced by
    bilinear interpolation); falls back to the 3-point vertex.
    以最大值周圍、高於其 50% 的連續樣本擬合拋物線（可抵抗雙線性內插造成
    的折線形狀）；不足時退回三點頂點法。

    Args:
        z: Positions / 位置。
        y: Signal (positive peak) / 訊號（正峰值）。
        i: Index of the maximum / 最大值索引。

    Returns:
        float: Refined peak position / 精修後的峰值位置。
    """
    half = 0.5 * y[i]
    lo, hi = i, i
    while lo > 0 and y[lo - 1] > half:
        lo -= 1
    while hi < len(y) - 1 and y[hi + 1] > half:
        hi += 1
    if hi - lo >= 4:
        zz = z[lo:hi + 1] - z[i]
        a, b, _ = np.polyfit(zz, y[lo:hi + 1], 2)
        if a < 0:
            vertex = -b / (2.0 * a)
            if z[lo] - z[i] <= vertex <= z[hi] - z[i]:
                return float(z[i] + vertex)
    if 0 < i < len(y) - 1:
        y0, y1, y2 = y[i - 1], y[i], y[i + 1]
        denom = y0 - 2.0 * y1 + y2
        if denom != 0 and np.isfinite(denom):
            offset = 0.5 * (y0 - y2) / denom
            if abs(offset) <= 1.0:
                return float(z[i] + offset * (z[i + 1] - z[i]))
    return float(z[i])


def compute_metrics(
    position: np.ndarray,
    intensity: np.ndarray,
    roi: RotatedRoi,
    settings: ProfileSettings,
) -> Dict[str, float]:
    """Computes background, peak, centroid, area and SNR of a profile.

    計算剖面的背景、峰值、質心、面積與 SNR。

    Args:
        position: Positions z (px) / 位置 z（像素）。
        intensity: Mean intensity / 平均強度。
        roi: ROI (for absolute coordinates and polarity) / ROI。
        settings: Settings / 設定。

    Returns:
        Dict[str, float]: Metrics keyed by ``METRIC_KEYS`` (Polarity as str).
            以 ``METRIC_KEYS`` 為鍵的指標（Polarity 為字串）。
    """
    z = np.asarray(position, dtype=np.float64)
    y = np.asarray(intensity, dtype=np.float64)
    finite = np.isfinite(y)
    out: Dict[str, float] = {k: float("nan") for k in METRIC_KEYS}
    if finite.sum() < 5:
        out["Polarity"] = "n/a"  # type: ignore[assignment]
        return out
    z, y = z[finite], y[finite]
    half = roi.dx / 2.0
    tail_edge = half * (1.0 - 2.0 * settings.tail_fraction)
    left = y[z <= -tail_edge]
    right = y[z >= tail_edge]
    tails = np.concatenate([left, right])
    if tails.size < 2:
        tails = y
    background = float(np.median(tails))
    std_left = float(np.std(left)) if left.size > 1 else float("nan")
    std_right = float(np.std(right)) if right.size > 1 else float("nan")
    noise = float(np.nanmean([std_left, std_right]))

    polarity = roi.polarity
    if polarity not in ("bright", "dark"):
        polarity = ("bright" if (y.max() - background) >= (background - y.min())
                    else "dark")
    sign = 1.0 if polarity == "bright" else -1.0
    signal = sign * (y - background)
    i_peak = int(np.argmax(signal))
    height = float(signal[i_peak])
    peak_pos = _parabolic_peak(z, signal, i_peak)

    # Contiguous region around the peak above threshold (centroid / area).
    # 峰值周圍高於門檻的連續區域（用於質心與面積）。
    thr = settings.signal_threshold * height
    lo = i_peak
    while lo > 0 and signal[lo - 1] > thr:
        lo -= 1
    hi = i_peak
    while hi < signal.size - 1 and signal[hi + 1] > thr:
        hi += 1
    seg_z, seg_s = z[lo:hi + 1], np.clip(signal[lo:hi + 1], 0.0, None)
    total = float(seg_s.sum())
    centroid = float((seg_z * seg_s).sum() / total) if total > 0 else peak_pos
    area = float(np.trapezoid(seg_s, seg_z)) if seg_z.size > 1 else 0.0

    px, py = roi.local_to_image(np.array([peak_pos]), np.array([0.0]))
    cx, cy = roi.local_to_image(np.array([centroid]), np.array([0.0]))
    out.update({
        "Polarity": polarity,  # type: ignore[dict-item]
        "Polarity_Sign": sign,
        "Background": background,
        "Background_Std": noise,
        "Peak_Value": float(y[i_peak]),
        "Peak_Height": height,
        "Peak_Pos_px": peak_pos,
        "Peak_X": float(px[0]),
        "Peak_Y": float(py[0]),
        "Centroid_px": centroid,
        "Centroid_X": float(cx[0]),
        "Centroid_Y": float(cy[0]),
        "Area": area,
        "SNR": height / noise if noise > 0 else float("inf"),
    })
    return out


def extract_roi_intensity_2d(
    image: np.ndarray,
    roi: RotatedRoi,
    step: float = 1.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Samples ROI as a 2-D intensity grid in local Position_px (u, v).

    以區域座標 Position_px（u／v）將 ROI 取樣成 2-D 強度陣列。

    Args:
        image: H×W luminance / 亮度影像。
        roi: Rotated ROI / 旋轉 ROI。
        step: Grid spacing in px (default 1) / 格點間距（像素，預設 1）。

    Returns:
        Tuple[np.ndarray, np.ndarray, np.ndarray]:
            ``(u_pos, v_pos, intensity)`` where intensity is shape
            ``(n_v, n_u)``; out-of-image samples are NaN.
            ``(u_pos, v_pos, intensity)``，強度形狀 ``(n_v, n_u)``；
            影像外為 NaN。
    """
    img = np.asarray(image, dtype=np.float64)
    if img.ndim != 2:
        raise ValueError("Image must be 2-D luminance / 影像須為 2-D 亮度陣列")
    if step <= 0:
        raise ValueError("step must be positive / step 必須為正數")
    half_u, half_v = roi.dx / 2.0, roi.dy / 2.0
    u = np.arange(-half_u, half_u + 1e-9, step, dtype=np.float64)
    v = np.arange(-half_v, half_v + 1e-9, step, dtype=np.float64)
    if u.size == 0:
        u = np.array([0.0], dtype=np.float64)
    if v.size == 0:
        v = np.array([0.0], dtype=np.float64)
    uu, vv = np.meshgrid(u, v)  # rows = v, cols = u
    xs, ys = roi.local_to_image(uu, vv)
    values = ndimage.map_coordinates(
        img, [ys.ravel(), xs.ravel()], order=1, mode="nearest",
        prefilter=False).reshape(uu.shape)
    h, w = img.shape
    inside = (xs >= -0.5) & (xs <= w - 0.5) & (ys >= -0.5) & (ys <= h - 0.5)
    values = np.where(inside, values, np.nan)
    return u, v, values


def extract_profile(
    image: np.ndarray,
    roi: RotatedRoi,
    settings: Optional[ProfileSettings] = None,
) -> LineProfile:
    """Extracts the line profile across ``roi`` (perpendicular to the line).

    擷取 ``roi`` 內垂直於線方向的 Line Profile。

    Args:
        image: H×W luminance image / 亮度影像。
        roi: Rotated ROI (profile along u, averaging along v).
            旋轉 ROI（沿 u 取剖面、沿 v 平均）。
        settings: Profile settings (default ``ProfileSettings()``) / 設定。

    Returns:
        LineProfile: Profile with metrics / 含指標的剖面。

    Raises:
        ValueError: Invalid image or settings / 影像或設定無效。
    """
    cfg = settings or ProfileSettings()
    cfg.validate()
    img = np.asarray(image, dtype=np.float64)
    if img.ndim != 2:
        raise ValueError("Image must be 2-D luminance / 影像須為 2-D 亮度陣列")
    if cfg.method == "project":
        pos, mean, std, count = _sample_projected(img, roi, cfg)
    else:
        pos, mean, std, count = _sample_interpolated(img, roi, cfg)
    sx, sy = roi.local_to_image(pos, np.zeros_like(pos))
    metrics = compute_metrics(pos, mean, roi, cfg)
    return LineProfile(
        roi=roi, position=pos, intensity=mean, intensity_std=std,
        count=np.asarray(count), sample_x=sx, sample_y=sy,
        metrics=metrics, settings=cfg)
