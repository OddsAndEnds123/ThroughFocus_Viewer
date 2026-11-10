"""Interactive rotated ROI graphics item / 可互動的旋轉 ROI 圖形物件。

Scene coordinates = image pixel-centre coordinates + 0.5 (pixel (0,0) covers
scene [0,1)×[0,1)). Item rotation = −Rota_Angle because Qt rotates clockwise
on a y-down screen while Rota_Angle is counter-clockwise.
場景座標 = 影像像素中心座標 + 0.5；因 Qt 在 y 向下的畫面上為順時針旋轉，而
Rota_Angle 為逆時針，所以 item 旋轉角 = −Rota_Angle。

Mouse / 滑鼠操作:
    * drag inside → move / 內部拖曳 → 移動
    * drag round handle above the box → rotate (Shift: 15° snap)
      拖曳上方圓形把手 → 旋轉（按 Shift 以 15° 為單位）
    * drag square handles on right / bottom edges → resize dx / dy
      拖曳右邊／下邊方形把手 → 調整 dx／dy
    * ``fixed_size`` True (Fixed size checkbox): no resize handles; W / H change
      only when typed in the Selected ROI fields
      ``fixed_size`` 為 True（勾選 Fixed size）：沒有縮放把手，只能輸入 W／H 改變
"""

from __future__ import annotations

import math
from typing import Callable, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QGraphicsItem, QGraphicsSceneMouseEvent,
                               QStyleOptionGraphicsItem, QWidget)

from viewer.roi import RotatedRoi, normalize_angle_deg

_HANDLE_PX = 7.0  # handle size in screen pixels / 把手螢幕尺寸
_ROT_OFFSET_PX = 12.0  # rotate-handle stem (shorter) / 旋轉把手桿長（縮短）

# Preview ROI_Rota modes / Preview ROI_Rota 模式
ROI_ROTA_CENTRI = "向心"
ROI_ROTA_UNIFIED = "統一旋轉"
ROI_ROTA_NONE = "None"
ROI_ROTA_MODES = (ROI_ROTA_CENTRI, ROI_ROTA_UNIFIED, ROI_ROTA_NONE)


class RoiItem(QGraphicsItem):
    """Graphics item bound to a ``RotatedRoi`` / 綁定 ``RotatedRoi`` 的圖形物件。

    Attributes:
        roi: Bound ROI model (updated in place) / 綁定的 ROI 模型（就地更新）。
        color: Display colour (matches the plot curve) / 顯示顏色（同曲線）。
        on_changed: Callback(item, final) during/after edits.
            編輯中／結束時呼叫的回呼函式 (item, final)。
        image_w, image_h: Image size for centre-axis guide / 影像尺寸（中心軸線用）。
    """

    def __init__(self, roi: RotatedRoi, color: QColor,
                 on_changed: Optional[Callable[["RoiItem", bool], None]] = None
                 ) -> None:
        """Initialises the item / 初始化物件。

        Args:
            roi: ROI model / ROI 模型。
            color: Colour / 顏色。
            on_changed: Change callback / 變更回呼。
        """
        super().__init__()
        self.roi = roi
        self.color = QColor(color)
        self.on_changed = on_changed
        # Called after a handle rotation is released with a new angle (not by
        # rotate_90 or typed values) / 旋轉把手放開且角度改變後呼叫
        self.on_rotated: Optional[Callable[["RoiItem"], None]] = None
        # Called after a mouse move is released at a new position (not by typed
        # values) / 滑鼠移動放開且位置改變後呼叫
        self.on_moved: Optional[Callable[["RoiItem"], None]] = None
        self._mode: Optional[str] = None
        self._press_scene = QPointF()
        self._press_roi: Optional[RotatedRoi] = None
        self._lod = 1.0
        # W/H ratio kept when resizing or typing W/H; None = free / 縮放或輸入時保持的寬高比
        self.aspect_lock: Optional[float] = None
        # True = size fixed, drag only moves / rotates / True＝尺寸固定，拖曳只移動或旋轉
        self.fixed_size = False
        # Image size (px) for centripetal axis / 影像尺寸（向心軸）
        self.image_w: float = 0.0
        self.image_h: float = 0.0
        # ROI_Rota display mode / ROI_Rota 顯示模式
        self.rota_mode: str = ROI_ROTA_NONE
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(10)
        self.sync_from_roi()

    def set_image_size(self, width: float, height: float) -> None:
        """Sets image size for the centripetal guide / 設定向心軸用的影像尺寸。"""
        self.prepareGeometryChange()
        self.image_w = float(max(width, 0.0))
        self.image_h = float(max(height, 0.0))
        self.update()

    def set_rota_mode(self, mode: str) -> None:
        """Sets ROI_Rota guide mode / 設定 ROI_Rota 輔助線模式。"""
        if mode not in ROI_ROTA_MODES:
            mode = ROI_ROTA_NONE
        self.rota_mode = mode
        self.prepareGeometryChange()
        self.update()

    # ----- geometry / 幾何 -----
    def _scale(self) -> float:
        """Scene units per screen pixel / 每螢幕像素的場景單位。"""
        return 1.0 / max(self._lod, 1e-6)

    def sync_from_roi(self) -> None:
        """Applies the ROI model to position/rotation / 將模型套用到位置與角度。"""
        self.prepareGeometryChange()
        self.setPos(self.roi.cx + 0.5, self.roi.cy + 0.5)
        self.setRotation(-self.roi.angle_deg)
        self.update()

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt API / Qt 介面
        """Bounding rectangle incl. handles / 含把手的外框（虛線不超出 ROI）。"""
        m = (_ROT_OFFSET_PX + 2 * _HANDLE_PX) * self._scale() + 2
        hw, hh = self.roi.dx / 2.0, self.roi.dy / 2.0
        return QRectF(-hw - m, -hh - m, 2 * hw + 2 * m, 2 * hh + 2 * m)

    def shape(self) -> QPainterPath:
        """Hit-test shape (box + handles) / 點擊判定形狀（框與把手）。"""
        path = QPainterPath()
        hw, hh = self.roi.dx / 2.0, self.roi.dy / 2.0
        path.addRect(QRectF(-hw, -hh, 2 * hw, 2 * hh))
        for c in self._handle_centres().values():
            r = _HANDLE_PX * self._scale()
            path.addEllipse(c, r, r)
        return path

    def set_fixed_size(self, fixed: bool) -> None:
        """Hides (True) or shows (False) the resize handles / 隱藏或顯示縮放把手。"""
        self.fixed_size = bool(fixed)
        self.prepareGeometryChange()
        self.update()

    def _handle_centres(self) -> dict:
        """Handle centres in local coords / 把手中心（區域座標）。"""
        hw, hh = self.roi.dx / 2.0, self.roi.dy / 2.0
        centres = {"rotate": QPointF(0.0, -hh - _ROT_OFFSET_PX * self._scale())}
        if not self.fixed_size:
            centres.update(resize_x=QPointF(hw, 0.0), resize_y=QPointF(0.0, hh))
        return centres

    # ----- painting / 繪製 -----
    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem,
              widget: Optional[QWidget] = None) -> None:
        """Paints box, profile axis and handles / 繪製外框、剖面軸與把手。"""
        self._lod = option.levelOfDetailFromTransform(painter.worldTransform())
        s = self._scale()
        hw, hh = self.roi.dx / 2.0, self.roi.dy / 2.0
        pen = QPen(self.color, (2.5 if self.isSelected() else 1.5) * s)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(-hw, -hh, 2 * hw, 2 * hh))
        # Dashed guide stays inside ROI / 虛線輔助線不超出 ROI
        if self.rota_mode == ROI_ROTA_CENTRI:
            axis_pen = QPen(self.color, 1.0 * s, Qt.PenStyle.DashLine)
            painter.setPen(axis_pen)
            self._paint_centri_axis(painter, s, hw, hh)
        elif self.rota_mode == ROI_ROTA_UNIFIED:
            axis_pen = QPen(self.color, 1.0 * s, Qt.PenStyle.DashLine)
            painter.setPen(axis_pen)
            self._paint_local_u_axis(painter, s, hw)
        # Handles / 把手
        hc = self._handle_centres()
        painter.setPen(QPen(self.color, 1.0 * s))
        painter.drawLine(QPointF(0, -hh), hc["rotate"])
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        r = _HANDLE_PX * 0.5 * s
        painter.drawEllipse(hc["rotate"], r * 1.2, r * 1.2)
        for key in ("resize_x", "resize_y"):
            if key in hc:
                c = hc[key]
                painter.drawRect(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r))
        # Label / 標籤
        painter.setPen(QPen(self.color))
        font = painter.font()
        font.setPointSizeF(max(9.0 * s, 0.5))
        painter.setFont(font)
        painter.drawText(QPointF(-hw, -hh - 3 * s), str(self.roi.roi_id))

    def _clip_axis_half_span(self, ux: float, uy: float, hw: float, hh: float
                             ) -> float:
        """Half-length of axis segment inside the ROI box / ROI 框內軸段半長。"""
        tx = hw / abs(ux) if abs(ux) > 1e-12 else 1e30
        ty = hh / abs(uy) if abs(uy) > 1e-12 else 1e30
        return float(min(tx, ty, max(hw, hh) * 2.0))

    def _paint_arrow(self, painter: QPainter, s: float, ux: float, uy: float,
                     tip: QPointF) -> None:
        """Small arrow at tip / 端點小箭頭。"""
        a = 5.0 * s
        px, py = -uy, ux
        painter.drawLine(tip, QPointF(tip.x() - ux * a + px * a * 0.6,
                                      tip.y() - uy * a + py * a * 0.6))
        painter.drawLine(tip, QPointF(tip.x() - ux * a - px * a * 0.6,
                                      tip.y() - uy * a - py * a * 0.6))

    def _paint_local_u_axis(self, painter: QPainter, s: float, hw: float) -> None:
        """Local u-axis dashed line inside ROI / ROI 內區域 u 軸虛線。"""
        painter.drawLine(QPointF(-hw, 0), QPointF(hw, 0))
        self._paint_arrow(painter, s, 1.0, 0.0, QPointF(hw, 0))

    def _paint_centri_axis(self, painter: QPainter, s: float,
                           hw: float, hh: float) -> None:
        """Centripetal dashed axis inside ROI (toward image centre).

        向心虛線軸（朝影像幾何中心），裁切在 ROI 內。
        """
        ux, uy = 1.0, 0.0
        if self.image_w > 1.0 and self.image_h > 1.0:
            ic = QPointF(self.image_w / 2.0, self.image_h / 2.0)
            local_c = self.mapFromScene(ic)
            length = math.hypot(local_c.x(), local_c.y())
            if length > 1e-3:
                # Direction from ROI centre toward image centre /
                # 由 ROI 中心指向影像中心
                ux, uy = local_c.x() / length, local_c.y() / length
        t = self._clip_axis_half_span(ux, uy, hw, hh)
        painter.drawLine(QPointF(-ux * t, -uy * t), QPointF(ux * t, uy * t))
        self._paint_arrow(painter, s, ux, uy, QPointF(ux * t, uy * t))

    # ----- interaction / 互動 -----
    def _hit_handle(self, local: QPointF) -> Optional[str]:
        """Returns the handle under ``local`` / 傳回滑鼠下的把手名稱。"""
        tol = _HANDLE_PX * self._scale()
        for key, c in self._handle_centres().items():
            if math.hypot(local.x() - c.x(), local.y() - c.y()) <= tol:
                return key
        return None

    def hoverMoveEvent(self, event) -> None:  # noqa: N802
        """Updates the cursor shape / 更新游標形狀。"""
        handle = self._hit_handle(event.pos())
        cursors = {"rotate": Qt.CursorShape.CrossCursor,
                   "resize_x": Qt.CursorShape.SizeHorCursor,
                   "resize_y": Qt.CursorShape.SizeVerCursor}
        self.setCursor(cursors.get(handle, Qt.CursorShape.SizeAllCursor))
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        """Starts move / rotate / resize (resize only if not fixed) / 開始移動、旋轉或縮放。"""
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._mode = self._hit_handle(event.pos()) or "move"
        self._press_scene = event.scenePos()
        self._press_roi = RotatedRoi(self.roi.cx, self.roi.cy, self.roi.dx,
                                     self.roi.dy, self.roi.angle_deg)
        if self.scene() is not None:
            self.scene().clearSelection()
        self.setSelected(True)
        event.accept()

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        """Applies the current drag: move, rotate or (not fixed) resize.

        套用拖曳：移動、旋轉，或（未固定尺寸時）縮放。
        """
        if self._mode is None or self._press_roi is None:
            super().mouseMoveEvent(event)
            return
        p0 = self._press_roi
        sp = event.scenePos()
        dxs, dys = sp.x() - self._press_scene.x(), sp.y() - self._press_scene.y()
        if self._mode == "move":
            self.roi.cx, self.roi.cy = p0.cx + dxs, p0.cy + dys
        elif self._mode == "rotate":
            # Handle sits on −v; angle of (centre→mouse) gives −v direction.
            # 把手在 −v 方向；以中心→滑鼠的方向求角度。
            vx, vy = sp.x() - (p0.cx + 0.5), sp.y() - (p0.cy + 0.5)
            ang = math.degrees(math.atan2(-vx, -vy))
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                ang = round(ang / 15.0) * 15.0
            self.roi.angle_deg = normalize_angle_deg(ang)
        else:
            local = self.mapFromScene(sp)
            if self._mode == "resize_x":
                self.roi.dx = max(4.0, round(2.0 * abs(local.x())))
                if self.aspect_lock:
                    self.roi.dy = max(1.0, round(self.roi.dx / self.aspect_lock))
            else:
                self.roi.dy = max(1.0, round(2.0 * abs(local.y())))
                if self.aspect_lock:
                    self.roi.dx = max(4.0, round(self.roi.dy * self.aspect_lock))
        self.sync_from_roi()
        if self.on_changed:
            self.on_changed(self, False)
        event.accept()

    def rotate_90(self) -> None:
        """Rotates +90° (CCW) about the centre, W/H unchanged / 繞中心逆時針轉 90°，W/H 不變。"""
        self.roi.angle_deg = normalize_angle_deg(self.roi.angle_deg + 90.0)
        self.sync_from_roi()
        if self.on_changed:
            self.on_changed(self, True)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        """Finishes the drag; a changed rotation calls ``on_rotated``, a changed
        position after a move calls ``on_moved`` / 結束拖曳；旋轉或移動有變化時呼叫回呼。
        """
        if self._mode is not None:
            mode, self._mode = self._mode, None
            if self.on_changed:
                self.on_changed(self, True)
            p0 = self._press_roi
            if (mode == "rotate" and self.on_rotated and p0 is not None
                    and self.roi.angle_deg != p0.angle_deg):
                self.on_rotated(self)
            elif (mode == "move" and self.on_moved and p0 is not None
                    and (self.roi.cx, self.roi.cy) != (p0.cx, p0.cy)):
                self.on_moved(self)
            event.accept()
            return
        super().mouseReleaseEvent(event)
