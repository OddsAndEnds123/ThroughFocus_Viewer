"""Group list (through-focus stacks) for ThroughFocus_Viewer.

圖集清單（通焦疊圖 group）— ThroughFocus_Viewer。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

import numpy as np
from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QLabel, QListWidget,
                               QListWidgetItem, QVBoxLayout, QWidget)

from viewer.gui.image_view import array_to_qimage
from viewer.image_io import LoadedImage
from viewer.roi import RotatedRoi
from viewer.tf_stack import TfMeta, format_dz

# Thumbnail / panel defaults / 縮圖與面板預設
THUMB_SIZE = QSize(160, 100)
PANEL_WIDTH = 200
IMAGE_FILTER = "Images (*.png *.bmp *.tif *.tiff *.jpg *.jpeg);;All (*.*)"
# Stacked-card offsets for group thumbnails (back → front) /
# 圖集疊層偏移（後→前）
_STACK_OFFSETS = ((10, -10), (5, -5), (0, 0))


@dataclass
class ImageSession:
    """One through-focus stack (or a single image) / 一組通焦疊圖（或單張影像）。

    ROIs are shared across all steps in the stack.
    ROI 在同一疊的所有步階共用。
    """

    frames: List[LoadedImage]
    displays: List[np.ndarray]
    metas: List[Optional[TfMeta]] = field(default_factory=list)
    label: str = ""
    current_step: int = 0
    rois: List[RotatedRoi] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.frames:
            raise ValueError("ImageSession needs at least one frame / 至少要有一張影像")
        if len(self.displays) != len(self.frames):
            raise ValueError("displays length must match frames / displays 長度須與 frames 相同")
        if not self.metas:
            self.metas = [None] * len(self.frames)
        elif len(self.metas) != len(self.frames):
            raise ValueError("metas length must match frames / metas 長度須與 frames 相同")
        self.current_step = max(0, min(self.current_step, len(self.frames) - 1))
        if not self.label:
            self.label = self._default_label()

    def _default_label(self) -> str:
        meta = self.metas[0] if self.metas else None
        if meta is not None and meta.field:
            return meta.field
        return os.path.basename(self.frames[0].path)

    @property
    def n_steps(self) -> int:
        return len(self.frames)

    @property
    def image(self) -> LoadedImage:
        return self.frames[self.current_step]

    @property
    def display(self) -> np.ndarray:
        return self.displays[self.current_step]

    @property
    def path(self) -> str:
        return self.image.path

    @property
    def meta(self) -> Optional[TfMeta]:
        return self.metas[self.current_step]

    def set_step(self, step: int) -> bool:
        """Sets current step; returns True if changed / 設定目前步階；有變更回傳 True。"""
        step = max(0, min(int(step), self.n_steps - 1))
        if step == self.current_step:
            return False
        self.current_step = step
        return True

    def step_label(self) -> str:
        """Short step/dz text for slider row / 滑桿列用的短標籤。"""
        meta = self.meta
        if meta is not None:
            return f"step {meta.step}/{meta.total}  {format_dz(meta.dz_mm)}"
        return f"step {self.current_step + 1}/{self.n_steps}"

    def list_label(self, index: int) -> str:
        """Groups list caption / 圖集清單標籤。"""
        meta = self.meta
        if self.n_steps > 1:
            if meta is not None:
                return (f"{index + 1} Group: {self.label}\n"
                        f"step {meta.step}/{meta.total}  {format_dz(meta.dz_mm)}")
            return (f"{index + 1} Group: {self.label}\n"
                    f"step {self.current_step + 1}/{self.n_steps}")
        return f"{index + 1} {os.path.basename(self.path)}"

    def thumbnail_icon(self) -> QIcon:
        """Single image or stacked-card group thumbnail / 單張或疊層圖集縮圖。"""
        return session_thumbnail(self.displays, self.current_step, THUMB_SIZE)


def _scaled_letterbox(display: np.ndarray, box: QSize) -> QPixmap:
    """Scale display into box with letterbox / 等比置中縮放到框內。"""
    canvas = QPixmap(box)
    canvas.fill(QColor(200, 200, 200))
    pm = QPixmap.fromImage(array_to_qimage(display)).scaled(
        box, Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation)
    painter = QPainter(canvas)
    painter.drawPixmap((box.width() - pm.width()) // 2,
                       (box.height() - pm.height()) // 2, pm)
    painter.end()
    return canvas


def fixed_thumbnail(display: np.ndarray, size: QSize = THUMB_SIZE) -> QIcon:
    """Letter-boxed thumbnail / 等比置中縮圖。"""
    return QIcon(_scaled_letterbox(display, size))


def session_thumbnail(
    displays: Sequence[np.ndarray],
    current_step: int = 0,
    size: QSize = THUMB_SIZE,
) -> QIcon:
    """Thumbnail; multi-frame groups get a stacked-card look.

    縮圖；多張圖集加上卡片疊層效果。
    """
    if not displays:
        blank = QPixmap(size)
        blank.fill(QColor(220, 220, 220))
        return QIcon(blank)
    if len(displays) == 1:
        return fixed_thumbnail(displays[0], size)

    # Front = current step; backs = other slices for depth cue /
    # 前景＝目前步階；背景取其他切片製造層次
    n = len(displays)
    front_i = max(0, min(int(current_step), n - 1))
    back_is = []
    if n >= 3:
        back_is = [0, n // 2]
    elif n == 2:
        back_is = [0 if front_i == 1 else 1]
    layer_idxs = back_is + [front_i]
    while len(layer_idxs) < 3:
        layer_idxs.insert(0, layer_idxs[0])

    canvas = QPixmap(size)
    canvas.fill(QColor(245, 245, 245))
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    # Content box leaves room for stack offsets / 內容區預留疊層偏移空間
    pad_x, pad_y = 12, 12
    inner = QSize(max(40, size.width() - pad_x), max(28, size.height() - pad_y))
    pen = QPen(QColor(160, 160, 160))
    pen.setWidth(1)

    for layer_i, (ox, oy) in zip(layer_idxs, _STACK_OFFSETS):
        thumb = _scaled_letterbox(displays[layer_i], inner)
        x = (size.width() - inner.width()) // 2 + ox - _STACK_OFFSETS[0][0] // 2
        y = (size.height() - inner.height()) // 2 + oy - _STACK_OFFSETS[0][1] // 2
        # Slight dim on back cards / 後層略暗
        if (ox, oy) != _STACK_OFFSETS[-1]:
            dim = QPixmap(thumb.size())
            dim.fill(QColor(230, 230, 230))
            dp = QPainter(dim)
            dp.setOpacity(0.55)
            dp.drawPixmap(0, 0, thumb)
            dp.setOpacity(1.0)
            dp.fillRect(dim.rect(), QColor(210, 210, 210, 80))
            dp.end()
            thumb = dim
        painter.drawPixmap(x, y, thumb)
        painter.setPen(pen)
        painter.drawRect(QRect(x, y, inner.width() - 1, inner.height() - 1))

    # Badge: frame count / 張數角標
    badge = f"×{n}"
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(67, 97, 238, 220))
    br = QRect(size.width() - 36, size.height() - 22, 32, 18)
    painter.drawRoundedRect(br, 4, 4)
    painter.setPen(QColor(255, 255, 255))
    painter.drawText(br, int(Qt.AlignmentFlag.AlignCenter), badge)
    painter.end()
    return QIcon(canvas)


class FrameListPanel(QWidget):
    """Resizable Groups list (IconMode) / 可調整寬度的圖集清單。"""

    frame_activated = Signal(int)  # session index

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(120)
        self.resize(PANEL_WIDTH, self.height())
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel("<b>Groups / 圖集</b>"))
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setFlow(QListWidget.Flow.TopToBottom)
        self.list.setWrapping(False)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setIconSize(THUMB_SIZE)
        self.list.setGridSize(QSize(THUMB_SIZE.width() + 16, THUMB_SIZE.height() + 44))
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.list.setWordWrap(True)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setSpacing(4)
        self.list.currentRowChanged.connect(self._on_row)
        lay.addWidget(self.list, 1)
        self._sessions: List[ImageSession] = []

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(PANEL_WIDTH, 400)

    def set_sessions(self, sessions: List[ImageSession], current: int = 0) -> None:
        """Rebuild list; select row while signals blocked (no activate recursion).

        重建清單；選列時封鎖訊號，避免 activate 遞迴。
        """
        self._sessions = sessions
        self.list.blockSignals(True)
        self.list.clear()
        for i, s in enumerate(sessions):
            item = QListWidgetItem(s.thumbnail_icon(), s.list_label(i))
            item.setData(Qt.ItemDataRole.UserRole, i)
            tip = s.path
            if s.n_steps > 1:
                tip = f"Group / 圖集: {s.label} ({s.n_steps} frames)\n{s.path}"
            item.setToolTip(tip)
            item.setSizeHint(self.list.gridSize())
            self.list.addItem(item)
        if 0 <= current < self.list.count():
            self.list.setCurrentRow(current)
        elif self.list.count() > 0:
            self.list.setCurrentRow(0)
        self.list.blockSignals(False)

    def update_session_row(self, si: int) -> None:
        """Refresh thumbnail/label for one session after step change.

        步階變更後更新該列縮圖與標籤。
        """
        if si < 0 or si >= len(self._sessions) or si >= self.list.count():
            return
        s = self._sessions[si]
        item = self.list.item(si)
        if item is None:
            return
        item.setIcon(s.thumbnail_icon())
        item.setText(s.list_label(si))
        tip = s.path
        if s.n_steps > 1:
            tip = f"Group / 圖集: {s.label} ({s.n_steps} frames)\n{s.path}"
        item.setToolTip(tip)

    def select_session(self, si: int) -> None:
        """Select list row for session index without rebuilding / 只選列不重建。"""
        self.list.blockSignals(True)
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item is not None and int(item.data(Qt.ItemDataRole.UserRole)) == si:
                self.list.setCurrentRow(row)
                break
        self.list.blockSignals(False)

    def _on_row(self, row: int) -> None:
        if row < 0:
            return
        item = self.list.item(row)
        if item is None:
            return
        self.frame_activated.emit(int(item.data(Qt.ItemDataRole.UserRole)))
