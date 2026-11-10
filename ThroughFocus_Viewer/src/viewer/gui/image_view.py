"""Zoomable image view with ROI drawing / 可縮放並可繪製 ROI 的影像檢視器。"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QGraphicsItem, QGraphicsPixmapItem, QGraphicsRectItem,
                               QGraphicsScene, QGraphicsView)


def array_to_qimage(display: np.ndarray) -> QImage:
    """Converts a uint8 gray/RGB array to QImage (copy) / 陣列轉 QImage。

    Args:
        display: H×W or H×W×3 uint8 array / uint8 陣列。

    Returns:
        QImage: Image copy / QImage 副本。
    """
    arr = np.ascontiguousarray(display)
    h, w = arr.shape[:2]
    if arr.ndim == 2:
        img = QImage(arr.data, w, h, arr.strides[0], QImage.Format.Format_Grayscale8)
    else:
        img = QImage(arr.data, w, h, arr.strides[0], QImage.Format.Format_RGB888)
    return img.copy()


def to_display(raw: np.ndarray) -> np.ndarray:
    """Scales a raw image (8/16/float, gray/RGB/RGBA) to uint8 for display.

    將原始影像縮放為 8-bit 供顯示（僅顯示用，不影響計算）。

    Args:
        raw: Raw array / 原始陣列。

    Returns:
        np.ndarray: uint8 array (gray or RGB) / uint8 陣列。
    """
    arr = raw[..., :3] if raw.ndim == 3 else raw
    if arr.dtype == np.uint8:
        return arr
    a = arr.astype(np.float64)
    lo, hi = float(np.percentile(a, 0.1)), float(np.percentile(a, 99.9))
    if hi <= lo:
        hi = lo + 1.0
    return np.clip((a - lo) / (hi - lo) * 255.0, 0, 255).astype(np.uint8)


def _to_gray_u8(display: np.ndarray) -> np.ndarray:
    """Gray uint8 from gray/RGB display / 灰階或 RGB 顯示圖轉 uint8 灰階。"""
    if display.ndim == 3:
        gray = (
            0.299 * display[..., 0].astype(np.float64)
            + 0.587 * display[..., 1].astype(np.float64)
            + 0.114 * display[..., 2].astype(np.float64)
        )
        return np.clip(gray, 0, 255).astype(np.uint8)
    return display


def apply_false_color(display: np.ndarray, cmap_name: str = "turbo") -> np.ndarray:
    """Maps intensity to RGB false-color (display only) / 強度偽彩成 RGB（僅顯示）。

    RGB input uses luminance first / 若為 RGB 先取亮度再上色。
    """
    gray = _to_gray_u8(display)
    from matplotlib import colormaps
    cmap = colormaps[cmap_name]
    norm = gray.astype(np.float64) / 255.0
    rgb = cmap(norm)[..., :3]
    return np.ascontiguousarray((rgb * 255.0).astype(np.uint8))


def apply_edge_mode(display: np.ndarray, cmap_name: str = "magma") -> np.ndarray:
    """Gradient-magnitude edge map as RGB (display only) / 梯度邊緣圖轉 RGB（僅顯示）。"""
    gray = _to_gray_u8(display).astype(np.float64)
    gy, gx = np.gradient(gray)
    edge = np.hypot(gx, gy)
    emax = float(np.nanmax(edge)) or 1.0
    norm = np.clip(edge / emax, 0.0, 1.0)
    from matplotlib import colormaps
    cmap = colormaps[cmap_name]
    rgb = cmap(norm)[..., :3]
    return np.ascontiguousarray((rgb * 255.0).astype(np.uint8))


class ImageView(QGraphicsView):
    """Image view: wheel zoom, middle/right-drag pan, rubber-band ROI drawing.

    影像檢視：滾輪縮放、中鍵／右鍵拖曳平移、繪製模式下左鍵拉框建立 ROI。

    Signals:
        roi_drawn(QRectF): Rectangle drawn in image coords / 繪製的矩形（影像座標）。
        cursor_moved(float, float): Cursor image coords / 游標影像座標。
    """

    roi_drawn = Signal(QRectF)
    cursor_moved = Signal(float, float)

    def __init__(self, parent=None) -> None:
        """Initialises the view / 初始化檢視器。"""
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QColor(40, 40, 40))
        self.setMouseTracking(True)
        self._pixmap_item: Optional[QGraphicsPixmapItem] = None
        self.draw_mode = False
        self._draw_start: Optional[QPointF] = None
        # (W, H) in image px: a click places a box of this FIXED size centred on
        # the cursor (None = free rubber band, previous behaviour)
        # 固定尺寸 (W, H)：點擊即以游標為中心放置此尺寸的框；None＝自由拉框（舊行為）
        self.fixed_size: Optional[Tuple[float, float]] = None
        self._rubber: Optional[QGraphicsRectItem] = None
        self._pan_start = None

    def set_image(self, display: np.ndarray) -> None:
        """Shows a new image and clears items / 顯示新影像並清除物件。

        Args:
            display: uint8 display array / 顯示用陣列。
        """
        self.scene().clear()
        self._pixmap_item = QGraphicsPixmapItem(QPixmap.fromImage(array_to_qimage(display)))
        self._pixmap_item.setTransformationMode(Qt.TransformationMode.FastTransformation)
        self._pixmap_item.setZValue(0)
        self.scene().addItem(self._pixmap_item)
        self.scene().setSceneRect(self._pixmap_item.boundingRect())
        self.fit()

    def clear_image(self) -> None:
        """Shows no image (empty list) / 不顯示影像（清單為空）。"""
        self.scene().clear()
        self._pixmap_item = None

    def replace_image(self, display: np.ndarray, fit: bool = False) -> None:
        """Swaps the shown image but keeps all items / 更換顯示影像但保留所有物件。

        Args:
            display: uint8 display array / 顯示用陣列。
            fit: If True, re-fit the view / True 時重新符合視窗。
        """
        if self._pixmap_item is None:
            self.set_image(display)
            return
        self._pixmap_item.setPixmap(QPixmap.fromImage(array_to_qimage(display)))
        self.scene().setSceneRect(self._pixmap_item.boundingRect())
        if fit:
            self.fit()

    def fit(self) -> None:
        """Fits the image in the view / 影像符合視窗大小。"""
        if self._pixmap_item is not None:
            self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Zooms around the cursor / 以游標為中心縮放。"""
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(factor, factor)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        """Starts drawing or panning / 開始繪製或平移。"""
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if (self.draw_mode and event.button() == Qt.MouseButton.LeftButton
                and self._pixmap_item is not None
                and not self._roi_at(event.position().toPoint())):
            self._draw_start = self.mapToScene(event.position().toPoint())
            self._rubber = self.scene().addRect(
                self._band_rect(self._draw_start, self._draw_start),
                QPen(QColor(255, 255, 0), 0, Qt.PenStyle.DashLine))
            self._rubber.setZValue(20)
            return
        super().mousePressEvent(event)

    def _band_rect(self, start: QPointF, pos: QPointF) -> QRectF:
        """Rubber band: fixed-size box centred on ``pos``, else start→pos.

        拉框：固定尺寸時為以 ``pos`` 為中心的框，否則為起點到目前位置。
        """
        if self.fixed_size is None:
            return QRectF(start, pos).normalized()
        w, h = self.fixed_size
        return QRectF(pos.x() - w / 2.0, pos.y() - h / 2.0, w, h)

    def _roi_at(self, pos) -> bool:
        """True if a selectable item (an ROI) is under ``pos``.

        游標下是否有可選取的物件（ROI）。Draw mode stays on after a drawing,
        so a press on an ROI must move it, not start a new rectangle.
        繪製模式畫完後仍開著，因此在 ROI 上按下時要移動它，而不是再畫一個新框。
        """
        flag = QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
        return any(it.flags() & flag for it in self.items(pos))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        """Updates rubber band / pan / cursor position / 更新拉框、平移與游標。"""
        sp = self.mapToScene(event.position().toPoint())
        self.cursor_moved.emit(sp.x() - 0.5, sp.y() - 0.5)
        if self._pan_start is not None:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y()))
            return
        if self._draw_start is not None and self._rubber is not None:
            self._rubber.setRect(self._band_rect(self._draw_start, sp))
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        """Finishes drawing or panning / 結束繪製或平移。"""
        if self._pan_start is not None:
            self._pan_start = None
            self.unsetCursor()
            return
        if self._draw_start is not None and self._rubber is not None:
            rect = self._rubber.rect()
            self.scene().removeItem(self._rubber)
            self._rubber, self._draw_start = None, None
            if self.fixed_size is not None or (rect.width() >= 3 and rect.height() >= 3):
                self.roi_drawn.emit(rect.translated(-0.5, -0.5))
            return
        super().mouseReleaseEvent(event)
