"""Iso-contour polylines + Bezier smoothing for Through-Focus Contour mode.

通焦 Contour 模式：強度等值線折線＋貝氏（三次）平滑。

Analytic function-fit is not wired in the Viewer yet; Contour uses measured
``ThroughFocusMap`` iso-levels smoothed with Catmull–Rom → cubic Bezier.
解析 Function-fit 尚未接入 Viewer；目前對量測通焦圖取等值線，再以
Catmull–Rom→三次貝氏曲線平滑（之後可換成解析 fit）。
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

import numpy as np

from viewer.tf_contour import DEFAULT_LEVELS, ThroughFocusMap

# (level, Nx2 array of [radial, focus] in map units)
ContourPoly = Tuple[float, np.ndarray]


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _edge_point(x0: float, y0: float, x1: float, y1: float,
                v0: float, v1: float, level: float) -> Tuple[float, float]:
    """Linear interpolate crossing on a cell edge / 單元邊上線性插值交點。"""
    if abs(v1 - v0) < 1e-30:
        t = 0.5
    else:
        t = (level - v0) / (v1 - v0)
    t = min(max(t, 0.0), 1.0)
    return (_lerp(x0, x1, t), _lerp(y0, y1, t))


def _marching_squares_level(
        z: np.ndarray, xs: np.ndarray, ys: np.ndarray, level: float,
) -> List[np.ndarray]:
    """Marching-squares segments for one iso-level / 單一等值面折線段。

    ``z`` is (n_y, n_x) with ``xs`` length n_x (radial) and ``ys`` length n_y
    (focus). Returns open polylines as lists of (x, y) = (radial, focus).
    """
    ny, nx = z.shape
    if ny < 2 or nx < 2:
        return []
    # Collect undirected edge segments, then chain / 先收集邊段再串成折線
    segs: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
    for j in range(ny - 1):
        y0, y1 = float(ys[j]), float(ys[j + 1])
        for i in range(nx - 1):
            x0, x1 = float(xs[i]), float(xs[i + 1])
            v00 = float(z[j, i])
            v10 = float(z[j, i + 1])
            v11 = float(z[j + 1, i + 1])
            v01 = float(z[j + 1, i])
            if not all(np.isfinite(v) for v in (v00, v10, v11, v01)):
                continue
            # Bit mask: corners above level / 角點高於等值的位元遮罩
            idx = (
                (1 if v00 >= level else 0)
                | (2 if v10 >= level else 0)
                | (4 if v11 >= level else 0)
                | (8 if v01 >= level else 0)
            )
            if idx in (0, 15):
                continue
            # Edge midpoints: bottom, right, top, left /
            # 邊交點：下、右、上、左
            b = _edge_point(x0, y0, x1, y0, v00, v10, level)
            r = _edge_point(x1, y0, x1, y1, v10, v11, level)
            t = _edge_point(x0, y1, x1, y1, v01, v11, level)
            l = _edge_point(x0, y0, x0, y1, v00, v01, level)
            # Standard MS cases (incl. simple saddle split) /
            # 標準 marching-squares（鞍點採簡單對角）
            table = {
                1: [(l, b)], 2: [(b, r)], 3: [(l, r)], 4: [(r, t)],
                5: [(l, t), (b, r)], 6: [(b, t)], 7: [(l, t)],
                8: [(t, l)], 9: [(b, t)], 10: [(b, l), (r, t)],
                11: [(r, t)], 12: [(r, l)], 13: [(b, r)], 14: [(b, l)],
            }
            segs.extend(table.get(idx, []))

    if not segs:
        return []

    # Chain segments into polylines / 邊段串成折線
    unused = list(segs)
    polys: List[List[Tuple[float, float]]] = []
    tol = 1e-9

    def close(a: Tuple[float, float], b: Tuple[float, float]) -> bool:
        return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol

    while unused:
        p0, p1 = unused.pop()
        chain = [p0, p1]
        grew = True
        while grew:
            grew = False
            for k in range(len(unused) - 1, -1, -1):
                a, b = unused[k]
                if close(chain[-1], a):
                    chain.append(b)
                    unused.pop(k)
                    grew = True
                elif close(chain[-1], b):
                    chain.append(a)
                    unused.pop(k)
                    grew = True
                elif close(chain[0], b):
                    chain.insert(0, a)
                    unused.pop(k)
                    grew = True
                elif close(chain[0], a):
                    chain.insert(0, b)
                    unused.pop(k)
                    grew = True
        if len(chain) >= 2:
            polys.append(chain)

    return [np.asarray(p, dtype=np.float64) for p in polys]


def bezier_smooth_polyline(
        pts: np.ndarray, samples_per_seg: int = 8,
) -> np.ndarray:
    """Catmull–Rom → cubic Bezier resampling / Catmull–Rom 轉三次貝氏重採樣。"""
    pts = np.asarray(pts, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[0] < 3 or pts.shape[1] != 2:
        return pts
    n = pts.shape[0]
    samples_per_seg = max(int(samples_per_seg), 2)
    out: List[np.ndarray] = []
    for i in range(n - 1):
        p0 = pts[i - 1] if i > 0 else pts[i]
        p1 = pts[i]
        p2 = pts[i + 1]
        p3 = pts[i + 2] if i + 2 < n else pts[i + 1]
        # Centripetal-ish CR → Bezier controls / CR 轉貝氏控制點
        b0 = p1
        b1 = p1 + (p2 - p0) / 6.0
        b2 = p2 - (p3 - p1) / 6.0
        b3 = p2
        ts = np.linspace(0.0, 1.0, samples_per_seg, endpoint=False)
        for t in ts:
            u = 1.0 - t
            out.append(
                (u ** 3) * b0
                + 3.0 * (u ** 2) * t * b1
                + 3.0 * u * (t ** 2) * b2
                + (t ** 3) * b3)
    out.append(pts[-1].copy())
    return np.asarray(out, dtype=np.float64)


def extract_contour_polylines(
        tf_map: ThroughFocusMap,
        levels: Sequence[float] = DEFAULT_LEVELS,
        *,
        bezier: bool = True,
        samples_per_seg: int = 6,
) -> List[ContourPoly]:
    """Iso-polylines in (radial, focus); optional Bezier smooth.

    以 (radial, focus) 座標回傳等值折線；可選貝氏平滑。
    """
    z = np.asarray(tf_map.intensity, dtype=np.float64)
    xs = np.asarray(tf_map.radial, dtype=np.float64)
    ys = np.asarray(tf_map.focus, dtype=np.float64)
    if z.ndim != 2 or xs.size < 2 or ys.size < 2:
        return []
    peak = float(np.nanmax(z)) if z.size else 0.0
    # If not peak-normalised, scale levels to data peak /
    # 未峰值歸一時，等值相對資料峰值縮放
    scale = 1.0
    if not getattr(tf_map, "normalized", True) and peak > 0:
        scale = peak
    result: List[ContourPoly] = []
    for lv in levels:
        level = float(lv) * scale
        if not np.isfinite(level):
            continue
        zmin, zmax = float(np.nanmin(z)), float(np.nanmax(z))
        if level < zmin or level > zmax:
            continue
        for poly in _marching_squares_level(z, xs, ys, level):
            if poly.shape[0] < 2:
                continue
            if bezier:
                poly = bezier_smooth_polyline(poly, samples_per_seg)
            result.append((float(lv), poly))
    return result
