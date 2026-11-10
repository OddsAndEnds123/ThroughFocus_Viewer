"""Rotated ROI geometry.

旋轉 ROI 幾何定義。

Coordinate conventions / 座標約定:
    * Image coordinates are in pixels with the CENTRE of pixel (row 0, col 0)
      at (x, y) = (0.0, 0.0); x to the right, y downward (numpy indexing).
      影像座標單位為像素，像素 (列 0, 行 0) 的「中心」為 (x, y) = (0.0, 0.0)；
      x 向右、y 向下（與 numpy 索引一致）。
    * Rota_Angle / Rota_Rad: ROI rotation, counter-clockwise as seen on screen
      (mathematical convention), normalised to (-90°, 90°].
      ROI 旋轉角，以螢幕上「逆時針」為正（數學慣例），範圍 (-90°, 90°]。
    * Local axes / 區域座標軸:
        u (profile axis, length dx) = (cos θ, -sin θ)  — 剖面方向（長度 dx）
        v (averaging axis, length dy) = (sin θ, cos θ) — 平均方向（長度 dy）
      A line feature runs along v; the line profile is sampled along u.
      線特徵沿 v 方向，Line Profile 沿 u 方向取樣。
    * X, Y: top-left corner of the UNROTATED rectangle, i.e. X = CX - dx/2,
      Y = CY - dy/2 (the rectangle is then rotated about (CX, CY)).
      X, Y：未旋轉矩形的左上角，即 X = CX - dx/2、Y = CY - dy/2
      （再以 (CX, CY) 為中心旋轉）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import List, Tuple

import numpy as np


def normalize_angle_deg(angle_deg: float) -> float:
    """Normalises an ROI angle to (-90, 90] degrees.

    將 ROI 角度正規化到 (-90, 90] 度。

    A rectangle rotated by 180° is identical, so the angle is taken mod 180.
    矩形旋轉 180° 後相同，因此角度以 180 取模。

    Args:
        angle_deg: Angle in degrees / 角度（度）。

    Returns:
        float: Normalised angle / 正規化後的角度。
    """
    a = math.fmod(angle_deg, 180.0)
    if a <= -90.0:
        a += 180.0
    elif a > 90.0:
        a -= 180.0
    return a


@dataclass
class RotatedRoi:
    """Rotated rectangular ROI / 旋轉矩形 ROI。

    Attributes:
        cx: Centre x (px) / 中心 x（像素）。
        cy: Centre y (px) / 中心 y（像素）。
        dx: Size along the profile axis u (px) / 剖面方向長度（像素）。
        dy: Size along the averaging axis v (px) / 平均方向長度（像素）。
        angle_deg: Rotation, CCW on screen, degrees / 旋轉角（螢幕逆時針，度）。
        roi_id: 1-based identifier / 編號（從 1 開始）。
        source: "manual" or "auto" / 來源：手動或自動。
        polarity: "bright", "dark" or "auto" / 線條極性。
        meta: Extra info (e.g. detection score) / 其他資訊（如偵測分數）。
    """

    cx: float
    cy: float
    dx: float
    dy: float
    angle_deg: float = 0.0
    roi_id: int = 0
    source: str = "manual"
    polarity: str = "auto"
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validates sizes and normalises the angle / 驗證尺寸並正規化角度。"""
        if self.dx <= 0 or self.dy <= 0:
            raise ValueError(
                f"ROI size must be positive (dx={self.dx}, dy={self.dy}) / "
                f"ROI 尺寸必須為正數")
        self.angle_deg = normalize_angle_deg(float(self.angle_deg))

    @property
    def angle_rad(self) -> float:
        """Rotation in radians (Rota_Rad) / 旋轉角（弧度）。"""
        return math.radians(self.angle_deg)

    @property
    def x(self) -> float:
        """Unrotated top-left X = CX - dx/2 / 未旋轉左上角 X。"""
        return self.cx - self.dx / 2.0

    @property
    def y(self) -> float:
        """Unrotated top-left Y = CY - dy/2 / 未旋轉左上角 Y。"""
        return self.cy - self.dy / 2.0

    @property
    def w(self) -> float:
        """ROI standard W = full size along u before rotation (alias of dx).

        ROI 標準 W：旋轉前沿 u 方向的完整寬度（等同 dx）。
        """
        return float(self.dx)

    @property
    def h(self) -> float:
        """ROI standard H = full size along v before rotation (alias of dy).

        ROI 標準 H：旋轉前沿 v 方向的完整高度（等同 dy）。
        """
        return float(self.dy)

    def bbox(self) -> Tuple[float, float, float, float]:
        """Axis-aligned bounding box of the rotated corners.

        旋轉後四角點的軸對齊外接矩形。

        Returns:
            Tuple[float, float, float, float]: (BBox_X, BBox_Y, BBox_W, BBox_H),
                top-left + size in px / 左上角與寬高（像素）。
        """
        pts = self.corners()
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    @property
    def u_axis(self) -> Tuple[float, float]:
        """Unit vector of the profile axis (image coords) / 剖面方向單位向量。"""
        t = self.angle_rad
        return (math.cos(t), -math.sin(t))

    @property
    def v_axis(self) -> Tuple[float, float]:
        """Unit vector of the averaging axis (image coords) / 平均方向單位向量。"""
        t = self.angle_rad
        return (math.sin(t), math.cos(t))

    @property
    def line_angle_deg(self) -> float:
        """Direction of a line lying along v, CCW in [0, 180) / 線方向角。"""
        return (self.angle_deg + 90.0) % 180.0

    def local_to_image(
        self, s: np.ndarray, t: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Maps local (s along u, t along v) to image (x, y).

        將區域座標（s 沿 u、t 沿 v）轉換為影像座標 (x, y)。

        Args:
            s: Offsets along u (px) / 沿 u 的位移。
            t: Offsets along v (px) / 沿 v 的位移。

        Returns:
            Tuple[np.ndarray, np.ndarray]: (x, y) arrays / (x, y) 陣列。
        """
        ux, uy = self.u_axis
        vx, vy = self.v_axis
        s_arr = np.asarray(s, dtype=np.float64)
        t_arr = np.asarray(t, dtype=np.float64)
        return (self.cx + s_arr * ux + t_arr * vx,
                self.cy + s_arr * uy + t_arr * vy)

    def corners(self) -> List[Tuple[float, float]]:
        """Corner points P1..P4 (TL, TR, BR, BL of the unrotated rect).

        四個角點 P1..P4（未旋轉矩形的左上、右上、右下、左下）。

        Returns:
            List[Tuple[float, float]]: Corner (x, y) list / 角點座標列表。
        """
        hs, ht = self.dx / 2.0, self.dy / 2.0
        s = np.array([-hs, hs, hs, -hs])
        t = np.array([-ht, -ht, ht, ht])
        xs, ys = self.local_to_image(s, t)
        return [(float(a), float(b)) for a, b in zip(xs, ys)]

    def contains(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Boolean mask of points inside the ROI / 點是否在 ROI 內的布林遮罩。

        Args:
            x: X coordinates / x 座標。
            y: Y coordinates / y 座標。

        Returns:
            np.ndarray: Boolean array / 布林陣列。
        """
        ux, uy = self.u_axis
        vx, vy = self.v_axis
        rx = np.asarray(x, dtype=np.float64) - self.cx
        ry = np.asarray(y, dtype=np.float64) - self.cy
        s = rx * ux + ry * uy
        t = rx * vx + ry * vy
        return (np.abs(s) <= self.dx / 2.0) & (np.abs(t) <= self.dy / 2.0)

    def within_image(self, width: float, height: float) -> bool:
        """True if every corner lies inside the image pixel grid.

        四角皆落在影像像素格內時為 True（半像素邊界：
        ``[-0.5, W-0.5]×[-0.5, H-0.5]``）。

        Args:
            width: Image width in pixels / 影像寬（像素）。
            height: Image height in pixels / 影像高（像素）。
        """
        w = float(width)
        h = float(height)
        if w <= 0 or h <= 0:
            return False
        x0, x1 = -0.5, w - 0.5
        y0, y1 = -0.5, h - 0.5
        for x, y in self.corners():
            if not (x0 <= x <= x1 and y0 <= y <= y1):
                return False
        return True

    def overlaps_image(self, width: float, height: float) -> bool:
        """True if the ROI AABB intersects the image (any in-image coverage).

        ROI 外接矩形與影像有交集時為 True；完全在影像外才為 False。
        """
        w = float(width)
        h = float(height)
        if w <= 0 or h <= 0:
            return False
        bx, by, bw, bh = self.bbox()
        return (bx <= w - 0.5 and by <= h - 0.5
                and (bx + bw) >= -0.5 and (by + bh) >= -0.5)
