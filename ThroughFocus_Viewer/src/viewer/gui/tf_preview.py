"""Through-focus preview under Groups (Qt image + aspect modes).

Groups 下方通焦預覽（Qt 影像；固定視窗／實際比例；含軸刻度）。
"""

from __future__ import annotations

import math
import os
import re
from typing import List, Optional, Tuple

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor, QContextMenuEvent, QFont, QImage, QPainter, QPainterPath, QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QMenu,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from viewer.contour_draw import extract_contour_polylines
from viewer.gui.image_view import apply_false_color, array_to_qimage
from viewer.tf_contour import DEFAULT_LEVELS, ThroughFocusMap
from viewer.ui_lang import LANG_EN, normalize_lang, tr

MODE_CONTOUR = "Contour"
MODE_FALSE_COLOR = "False Color"
PREVIEW_MODES = (MODE_CONTOUR, MODE_FALSE_COLOR)

# Aspect keys (stable in settings; labels follow Lang) /
# Aspect 鍵值（設定檔穩定；顯示文字隨語言）
ASPECT_FILL = "固定視窗"
ASPECT_PHYSICAL = "實際比例"
ASPECT_MODES = (ASPECT_FILL, ASPECT_PHYSICAL)

# Display aspect clamp so extreme Focus/Radial (e.g. ±15 mm vs ±0.12 mm)
# stays readable / 極端軸比時限制顯示長寬比以便閱讀
_ASPECT_LO = 0.25
_ASPECT_HI = 4.0
# Left / top / bottom margins; right leaves room for intensity scale /
# 左／上／下邊距；右側預留強度表
_ML, _MT, _MB = 52, 10, 36
_MR = 78  # colorbar + labels / 色條＋數值
_ML0, _MR0, _MT0, _MB0 = 6, 58, 6, 6
_CB_W = 12
_CB_GAP = 6


class _TfImageLabel(QLabel):
    """QLabel that always offers a right-click Save Image menu.

    右鍵一律可開「另存圖片」選單的 QLabel。
    """

    save_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        menu = QMenu(self)
        act = menu.addAction("Save Image... / 另存圖片")
        chosen = menu.exec(event.globalPos())
        if chosen == act:
            self.save_requested.emit()
        event.accept()


def _intensity_to_u8(intensity: np.ndarray) -> np.ndarray:
    """Peak-scale intensity -> uint8 gray for display / 顯示用峰值縮放灰階。"""
    a = np.nan_to_num(np.asarray(intensity, dtype=np.float64), nan=0.0)
    peak = float(np.nanmax(a)) if a.size else 0.0
    if not np.isfinite(peak) or peak <= 0:
        return np.zeros(a.shape, dtype=np.uint8)
    return np.clip(a / peak * 255.0, 0, 255).astype(np.uint8)


def render_tf_image(tf_map: ThroughFocusMap, mode: str) -> Tuple[np.ndarray, str]:
    """Build RGB preview image + title / 產生 RGB 預覽圖與標題。"""
    gray = _intensity_to_u8(tf_map.intensity)
    if mode == MODE_FALSE_COLOR:
        rgb = apply_false_color(gray, "turbo")
        title = f"ROI {tf_map.roi_id}  False Color  ({tf_map.n_frames} steps)"
    else:
        # Soft gray underlay; Bezier iso-lines drawn in compose /
        # 淡灰底圖；等高線（貝氏）於 compose 向量繪製
        soft = (gray.astype(np.float64) * 0.55 + 40.0).clip(0, 255).astype(np.uint8)
        rgb = np.stack([soft, soft, soft], axis=-1)
        title = (
            f"ROI {tf_map.roi_id}  Contour+Bezier  ({tf_map.n_frames} steps)")
    return np.ascontiguousarray(rgb), title


def _map_to_plot(radial: float, focus: float, plot: QRectF,
                 r0: float, r1: float, f_top: float, f_bot: float) -> QPointF:
    """Physical (radial, focus) → plot pixel / 物理座標→繪圖區像素。"""
    if r1 == r0:
        fx = 0.5
    else:
        fx = (radial - r0) / (r1 - r0)
    if f_top == f_bot:
        fy = 0.5
    else:
        fy = (f_top - focus) / (f_top - f_bot)
    fx = min(max(fx, 0.0), 1.0)
    fy = min(max(fy, 0.0), 1.0)
    return QPointF(
        plot.left() + fx * plot.width(),
        plot.top() + fy * plot.height())


def _intensity_range(tf_map: ThroughFocusMap) -> Tuple[float, float]:
    """Display intensity min/max for the scale / 強度表顯示範圍。"""
    a = np.asarray(tf_map.intensity, dtype=np.float64)
    if a.size == 0:
        return 0.0, 1.0
    zmin = float(np.nanmin(a))
    zmax = float(np.nanmax(a))
    if not np.isfinite(zmin) or not np.isfinite(zmax):
        return 0.0, 1.0
    if getattr(tf_map, "normalized", True):
        # Peak-norm maps use 0..1 scale / 峰值歸一以 0..1 為表尺
        return 0.0, 1.0
    if abs(zmax - zmin) < 1e-30:
        return zmin, zmin + 1.0
    return zmin, zmax


def _draw_intensity_scale(
        painter: QPainter, tf_map: ThroughFocusMap, plot: QRectF,
        mode: str, lang: str,
) -> None:
    """Colorbar + intensity labels (強度表) to the right of the plot.

    圖右側色條與強度數值（強度表）。
    """
    zmin, zmax = _intensity_range(tf_map)
    cb = QRectF(
        plot.right() + _CB_GAP, plot.top(), _CB_W, max(plot.height(), 10))
    h = max(int(round(cb.height())), 2)
    w = max(int(round(cb.width())), 2)
    # Top = high intensity / 上方＝高強度
    ramp = np.linspace(255.0, 0.0, h).astype(np.uint8)
    gray = np.repeat(ramp.reshape(h, 1), w, axis=1)
    if mode == MODE_FALSE_COLOR:
        rgb = apply_false_color(gray, "turbo")
    else:
        rgb = np.stack([gray, gray, gray], axis=-1)
    qimg = array_to_qimage(np.ascontiguousarray(rgb))
    painter.drawPixmap(cb.toRect(), QPixmap.fromImage(qimg))
    painter.setPen(QPen(QColor(200, 200, 200)))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(cb)

    font = QFont("Segoe UI", 7)
    painter.setFont(font)
    painter.setPen(QColor(220, 220, 220))
    # Title / 標題
    painter.drawText(
        QRectF(cb.right() + 2, cb.top() - 14, 52, 14),
        int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
        tr(lang, "intensity_short"))

    def y_for(val: float) -> float:
        if zmax == zmin:
            return cb.center().y()
        t = (zmax - val) / (zmax - zmin)
        return cb.top() + min(max(t, 0.0), 1.0) * cb.height()

    # Scale ticks: max / mid / min；Contour 另標 Fig.2 等值（原始強度則×peak）
    ticks = [zmax, 0.5 * (zmin + zmax), zmin]
    if mode == MODE_CONTOUR:
        peak = zmax if zmax > 0 else 1.0
        # DEFAULT_LEVELS are peak-fractions; scale when raw /
        # DEFAULT_LEVELS 為峰值分數；原始強度時乘 peak
        scale = 1.0 if getattr(tf_map, "normalized", True) else peak
        ticks = [zmax]
        for lv in sorted(DEFAULT_LEVELS, reverse=True):
            val = float(lv) * scale
            if zmin - 1e-12 <= val <= zmax + 1e-12:
                ticks.append(val)
        ticks.append(zmin)
        uniq: List[float] = []
        for t in ticks:
            if not uniq or abs(t - uniq[-1]) > 1e-9 * max(1.0, abs(t)):
                uniq.append(t)
        ticks = uniq

    for val in ticks:
        y = y_for(val)
        painter.setPen(QPen(QColor(200, 200, 200)))
        painter.drawLine(
            QPointF(cb.right(), y), QPointF(cb.right() + 3, y))
        painter.setPen(QColor(230, 230, 230))
        painter.drawText(
            QRectF(cb.right() + 4, y - 7, 48, 14),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            _fmt_tick(val))


def _draw_contour_overlay(
        painter: QPainter, tf_map: ThroughFocusMap, plot: QRectF,
        r0: float, r1: float, f_top: float, f_bot: float,
) -> None:
    """Draw Bezier-smoothed iso-lines + level tags / 繪製貝氏等高線與標註。"""
    polys = extract_contour_polylines(tf_map, bezier=True)
    if not polys:
        return
    pen = QPen(QColor(20, 20, 20))
    pen.setWidth(1)
    pen.setCosmetic(True)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    font = QFont("Segoe UI", 7)
    painter.setFont(font)
    labeled: set = set()
    for level, pts in polys:
        if pts.shape[0] < 2:
            continue
        path = QPainterPath()
        p0 = _map_to_plot(
            float(pts[0, 0]), float(pts[0, 1]), plot, r0, r1, f_top, f_bot)
        path.moveTo(p0)
        for k in range(1, pts.shape[0]):
            path.lineTo(_map_to_plot(
                float(pts[k, 0]), float(pts[k, 1]),
                plot, r0, r1, f_top, f_bot))
        painter.drawPath(path)
        # One label per level (midpoint of longest poly) /
        # 每個等值只標一次（取較長折線中點）
        key = round(float(level), 6)
        if key in labeled:
            continue
        mid = pts[pts.shape[0] // 2]
        mp = _map_to_plot(
            float(mid[0]), float(mid[1]), plot, r0, r1, f_top, f_bot)
        if not plot.contains(mp):
            continue
        labeled.add(key)
        painter.setPen(QColor(255, 230, 80))
        painter.drawText(
            QRectF(mp.x() - 18, mp.y() - 8, 36, 14),
            int(Qt.AlignmentFlag.AlignCenter),
            f"{level:g}")
        painter.setPen(pen)


def _nice_ticks(vmin: float, vmax: float, n: int = 5) -> List[float]:
    """Nice tick values covering [vmin, vmax] / 涵蓋區間的漂亮刻度。"""
    if not np.isfinite(vmin) or not np.isfinite(vmax):
        return [0.0]
    if abs(vmax - vmin) < 1e-30:
        return [float(vmin)]
    lo, hi = (vmin, vmax) if vmin <= vmax else (vmax, vmin)
    raw = (hi - lo) / max(n - 1, 1)
    exp = math.floor(math.log10(raw)) if raw > 0 else 0
    base = 10.0 ** exp
    step = base
    for m in (1.0, 2.0, 5.0, 10.0):
        if raw <= m * base:
            step = m * base
            break
    t0 = math.floor(lo / step) * step
    ticks: List[float] = []
    t = t0
    for _ in range(64):
        if t >= lo - step * 1e-9 and t <= hi + step * 1e-9:
            ticks.append(float(t))
        t += step
        if t > hi + step * 1.5:
            break
    return ticks or [float(lo), float(hi)]


def _equal_div_ticks(vmin: float, vmax: float, n_div: int = 4) -> List[float]:
    """Equal-interval ticks (n_div parts → n_div+1 marks) / 等分刻度。"""
    if not np.isfinite(vmin) or not np.isfinite(vmax):
        return [0.0]
    if abs(vmax - vmin) < 1e-30:
        return [float(vmin)]
    lo, hi = (vmin, vmax) if vmin <= vmax else (vmax, vmin)
    n_div = max(int(n_div), 1)
    return [float(lo + (hi - lo) * i / n_div) for i in range(n_div + 1)]


def _fmt_tick(v: float) -> str:
    """Format numbers without scientific notation (15000 not 1.5e+04).

    數字格式：不用科學記號（寫 15000，不寫 1.5e+04）。
    """
    if not np.isfinite(v):
        return "—"
    av = abs(float(v))
    if av == 0.0:
        return "0"
    # Exact (or nearly) integers / 整數（或近似整數）
    if abs(v - round(v)) < 1e-9 * max(1.0, av):
        return f"{int(round(v))}"
    # Fixed-point; strip trailing zeros / 定點小數，去掉尾隨 0
    if av >= 100:
        s = f"{v:.2f}"
    elif av >= 1:
        s = f"{v:.4f}"
    elif av >= 1e-3:
        s = f"{v:.6f}"
    else:
        s = f"{v:.8f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def physical_hw_ratio(tf_map: ThroughFocusMap) -> Tuple[float, bool]:
    """Return (height/width, clamped?) from Focus/Radial spans.

    由 Focus／Radial 實際範圍回傳（高/寬, 是否被夾限）。
    """
    r0, r1 = float(tf_map.radial[0]), float(tf_map.radial[-1])
    f0, f1 = float(tf_map.focus[0]), float(tf_map.focus[-1])
    rw = max(abs(r1 - r0), 1e-12)
    fh = max(abs(f1 - f0), 1e-12)
    ratio = fh / rw
    clamped = ratio < _ASPECT_LO or ratio > _ASPECT_HI
    ratio = min(max(ratio, _ASPECT_LO), _ASPECT_HI)
    return ratio, clamped


def plot_rect_for_aspect(canvas_w: int, canvas_h: int, aspect: str,
                         tf_map: ThroughFocusMap,
                         show_axes: bool = True) -> QRectF:
    """Inner plot rect: fill panel or physical aspect / 填滿或實際比例。"""
    # Always reserve right margin for intensity scale / 右側一律留強度表
    ml, mt, mb = ((_ML, _MT, _MB) if show_axes else (_ML0, _MT0, _MB0))
    mr = _MR if show_axes else _MR0
    avail = QRectF(
        ml, mt,
        max(canvas_w - ml - mr, 10),
        max(canvas_h - mt - mb, 10))
    if aspect == ASPECT_FILL:
        return avail
    hw_ratio, _ = physical_hw_ratio(tf_map)
    aw, ah = avail.width(), avail.height()
    if aw / max(ah, 1e-6) > 1.0 / max(hw_ratio, 1e-6):
        ph = ah
        pw = ph / hw_ratio
    else:
        pw = aw
        ph = pw * hw_ratio
    x = avail.x() + (aw - pw) / 2.0
    y = avail.y() + (ah - ph) / 2.0
    return QRectF(x, y, pw, ph)


def compose_tf_pixmap(rgb_flipud: np.ndarray, tf_map: ThroughFocusMap,
                      aspect: str, canvas_w: int, canvas_h: int,
                      show_axes: bool = True,
                      focus_step_index: Optional[int] = None,
                      mode: str = MODE_FALSE_COLOR,
                      lang: str = LANG_EN) -> QPixmap:
    """RGB (+ Contour Bezier lines + axes + step marker) / 影像合成。"""
    lang = normalize_lang(lang)
    unit = tf_map.unit
    r0, r1 = float(tf_map.radial[0]), float(tf_map.radial[-1])
    f0, f1 = float(tf_map.focus[0]), float(tf_map.focus[-1])
    # After flipud: top of image = focus[-1], bottom = focus[0]
    f_top, f_bot = f1, f0

    pm = QPixmap(canvas_w, canvas_h)
    pm.fill(QColor(30, 30, 30))
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    plot = plot_rect_for_aspect(
        canvas_w, canvas_h, aspect, tf_map, show_axes=show_axes)
    qimg = array_to_qimage(rgb_flipud)
    src = QPixmap.fromImage(qimg)
    painter.drawPixmap(plot.toRect(), src)

    # Contour mode: Bezier iso-lines on top of soft gray underlay /
    # Contour 模式：淡灰底圖上疊貝氏等高線
    if mode == MODE_CONTOUR:
        painter.setClipRect(plot)
        _draw_contour_overlay(
            painter, tf_map, plot, r0, r1, f_top, f_bot)
        painter.setClipping(False)

    # Focus-step marker (display only) / Focus 步階標線（僅顯示）
    n_f = int(np.asarray(tf_map.focus).size)
    if (focus_step_index is not None and n_f >= 1
            and 0 <= int(focus_step_index) < n_f):
        fi = int(focus_step_index)
        fval = float(tf_map.focus[fi])
        if f_top == f_bot:
            fy = 0.5
        else:
            fy = (f_top - fval) / (f_top - f_bot)
        fy = min(max(fy, 0.0), 1.0)
        y = plot.top() + fy * plot.height()
        step_pen = QPen(QColor(255, 64, 64))
        step_pen.setWidth(2)
        painter.setPen(step_pen)
        painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))

    pen = QPen(QColor(200, 200, 200))
    pen.setWidth(1)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(plot)

    # Intensity scale (colorbar + level table) / 強度表（色條＋層級）
    _draw_intensity_scale(painter, tf_map, plot, mode, lang)

    if show_axes:
        font = QFont("Segoe UI", 8)
        painter.setFont(font)
        painter.setPen(QColor(210, 210, 210))

        for tv in _nice_ticks(r0, r1, 5):
            if r1 == r0:
                fx = 0.5
            else:
                fx = (tv - r0) / (r1 - r0)
            fx = min(max(fx, 0.0), 1.0)
            x = plot.left() + fx * plot.width()
            painter.drawLine(QPointF(x, plot.bottom()),
                             QPointF(x, plot.bottom() + 4))
            painter.drawText(
                QRectF(x - 28, plot.bottom() + 4, 56, 14),
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
                _fmt_tick(tv))
        painter.drawText(
            QRectF(plot.left(), canvas_h - 16, plot.width(), 14),
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
            tr(lang, "radial_axis", unit=unit))

        # Focus: 4 equal divisions / Focus：四等分刻度
        for tv in _equal_div_ticks(min(f_bot, f_top), max(f_bot, f_top), 4):
            if f_top == f_bot:
                fy = 0.5
            else:
                fy = (f_top - tv) / (f_top - f_bot)
            fy = min(max(fy, 0.0), 1.0)
            y = plot.top() + fy * plot.height()
            painter.drawLine(QPointF(plot.left() - 4, y),
                             QPointF(plot.left(), y))
            painter.drawText(
                QRectF(2, y - 7, _ML - 8, 14),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                _fmt_tick(tv))
        painter.save()
        painter.translate(14, plot.center().y())
        painter.rotate(-90)
        painter.drawText(
            QRectF(-plot.height() / 2, -8, plot.height(), 16),
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
            tr(lang, "focus_axis", unit=unit))
        painter.restore()
    painter.end()
    return pm


def export_tf_png_bytes(
        tf_map: ThroughFocusMap,
        mode: str = MODE_FALSE_COLOR,
        aspect: str = ASPECT_PHYSICAL,
        width: int = 640,
        height: int = 480,
        show_axes: bool = True,
        lang: str = LANG_EN,
) -> bytes:
    """Compose TF preview PNG for Excel embed / 合成通焦預覽 PNG（嵌入 Excel）。"""
    if mode not in PREVIEW_MODES:
        mode = MODE_FALSE_COLOR
    if aspect not in ASPECT_MODES:
        aspect = ASPECT_PHYSICAL
    rgb, _ = render_tf_image(tf_map, mode)
    rgb = np.ascontiguousarray(np.flipud(rgb))
    pm = compose_tf_pixmap(
        rgb, tf_map, aspect, max(width, 220), max(height, 180),
        show_axes=show_axes, mode=mode, lang=lang)
    from PySide6.QtCore import QBuffer, QIODevice
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    ok = pm.save(buf, "PNG")
    data = bytes(buf.data())
    buf.close()
    if ok and data:
        return data
    # Fallback via PIL if Qt save empty / Qt 失敗時改 PIL
    from PIL import Image as PILImage
    qimg = pm.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = qimg.width(), qimg.height()
    ptr = qimg.bits()
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape((h, w, 4)).copy()
    bio = __import__("io").BytesIO()
    PILImage.fromarray(arr, "RGBA").save(bio, format="PNG")
    return bio.getvalue()


class TfPreviewPanel(QWidget):
    """Groups-below through-focus preview / Groups 下方通焦預覽。"""

    mode_changed = Signal(str)
    aspect_changed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(280)
        self.setMinimumWidth(280)
        self._last_map: Optional[ThroughFocusMap] = None
        self._mode = MODE_FALSE_COLOR
        self._aspect = ASPECT_PHYSICAL
        self._lang = LANG_EN
        self._rgb: Optional[np.ndarray] = None
        self._focus_step: Optional[int] = None
        self._save_folder: str = "TF"
        self._save_roi_id: int = 0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        # Title alone — avoid crowding controls onto one narrow row /
        # 標題單獨一列，避免窄面板上擠在一起
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(QLabel("<b>Through-Focus / 通焦預覽</b>"))
        head.addStretch(1)
        lay.addLayout(head)

        # Two control rows + horizontal scroll when pane is narrow /
        # 控制項分兩列；面板過窄時可左右捲動
        ctrl_host = QWidget()
        ctrl_lay = QVBoxLayout(ctrl_host)
        ctrl_lay.setContentsMargins(0, 0, 0, 0)
        ctrl_lay.setSpacing(4)

        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(6)
        row1.addWidget(QLabel("Mode"))
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems(list(PREVIEW_MODES))
        self.cmb_mode.setMinimumWidth(110)
        self.cmb_mode.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.cmb_mode.setToolTip(
            "Contour = iso-lines (Bezier smooth; analytic fit later); "
            "False Color = turbo / "
            "Contour＝等值線（貝氏平滑；日後接解析 fit）；"
            "False Color＝turbo 偽彩")
        self.cmb_mode.setCurrentText(MODE_FALSE_COLOR)
        self.cmb_mode.currentTextChanged.connect(self._on_mode)
        row1.addWidget(self.cmb_mode)
        row1.addStretch(1)
        ctrl_lay.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(6)
        self.lbl_aspect = QLabel("Aspect")
        row2.addWidget(self.lbl_aspect)
        self.cmb_aspect = QComboBox()
        self.cmb_aspect.setMinimumWidth(100)
        self.cmb_aspect.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.cmb_aspect.setToolTip(
            "Fixed Window = fill panel; Physical = Focus/Radial ratio "
            "(clamped if extreme) / "
            "固定視窗＝填滿面板；實際比例＝依 Focus／Radial（極端比夾限）")
        self._rebuild_aspect_combo(ASPECT_PHYSICAL)
        self.cmb_aspect.currentIndexChanged.connect(self._on_aspect_index)
        row2.addWidget(self.cmb_aspect)
        self.chk_axes = QCheckBox("Axes")
        self.chk_axes.setChecked(True)
        self.chk_axes.setToolTip(
            "Show Focus/Radial ticks and labels / 顯示 Focus／Radial 座標刻度")
        self.chk_axes.toggled.connect(self._on_axes)
        row2.addWidget(self.chk_axes)
        self.btn_save_img = QPushButton("Save Image")
        self.btn_save_img.setToolTip(
            "Save through-focus PNG / 另存通焦圖（亦可用右鍵）")
        self.btn_save_img.clicked.connect(self._save_image_dialog)
        row2.addWidget(self.btn_save_img)
        row2.addStretch(1)
        ctrl_lay.addLayout(row2)

        ctrl_scroll = QScrollArea()
        ctrl_scroll.setWidget(ctrl_host)
        ctrl_scroll.setWidgetResizable(True)
        ctrl_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        ctrl_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        ctrl_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        ctrl_scroll.setMinimumHeight(56)
        ctrl_scroll.setMaximumHeight(72)
        ctrl_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay.addWidget(ctrl_scroll)

        self.lbl_title = QLabel("No ROI / 尚未選取 ROI")
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_title.setStyleSheet("color:#444; font-size:11px;")
        self.lbl_title.setMinimumHeight(18)
        lay.addWidget(self.lbl_title)

        self.img_label = _TfImageLabel()
        self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_label.setMinimumHeight(180)
        self.img_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.img_label.setStyleSheet(
            "background:#1e1e1e; border:1px solid #555;")
        self.img_label.setScaledContents(False)
        self.img_label.setToolTip(
            "Right-click → Save Image / 右鍵 → 另存圖片")
        self.img_label.save_requested.connect(self._save_image_dialog)
        lay.addWidget(self.img_label, 1)

        self.lbl_axes = QLabel("")
        self.lbl_axes.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_axes.setStyleSheet("color:#666; font-size:10px;")
        self.lbl_axes.setWordWrap(True)
        lay.addWidget(self.lbl_axes)

        self.clear("No ROI / 尚未選取 ROI")

    def _on_mode(self, mode: str) -> None:
        if mode not in PREVIEW_MODES:
            mode = MODE_FALSE_COLOR
        self._mode = mode
        self.mode_changed.emit(mode)
        if self._last_map is not None:
            self.show_map(self._last_map)

    def _rebuild_aspect_combo(self, select: str = ASPECT_PHYSICAL) -> None:
        """Refill Aspect items for current language / 依語言重建 Aspect 選項。"""
        if select not in ASPECT_MODES:
            select = ASPECT_PHYSICAL
        self.cmb_aspect.blockSignals(True)
        self.cmb_aspect.clear()
        for key in ASPECT_MODES:
            label_key = (
                "aspect_fill" if key == ASPECT_FILL else "aspect_physical")
            self.cmb_aspect.addItem(tr(self._lang, label_key), key)
        idx = self.cmb_aspect.findData(select)
        self.cmb_aspect.setCurrentIndex(idx if idx >= 0 else 0)
        self.cmb_aspect.blockSignals(False)
        self._aspect = str(self.cmb_aspect.currentData() or ASPECT_PHYSICAL)

    def _on_aspect_index(self, _index: int = 0) -> None:
        aspect = str(self.cmb_aspect.currentData() or ASPECT_PHYSICAL)
        if aspect not in ASPECT_MODES:
            aspect = ASPECT_PHYSICAL
        self._aspect = aspect
        self.aspect_changed.emit(aspect)
        if self._rgb is not None:
            self._apply_pixmap()
            self._refresh_axes_caption()

    def _on_axes(self, _checked: bool = False) -> None:
        if self._rgb is not None:
            self._apply_pixmap()
            self._refresh_axes_caption()

    def mode(self) -> str:
        return self.cmb_mode.currentText()

    def set_mode(self, mode: str) -> None:
        if mode not in PREVIEW_MODES:
            mode = MODE_FALSE_COLOR
        idx = self.cmb_mode.findText(mode)
        if idx >= 0:
            self.cmb_mode.setCurrentIndex(idx)

    def aspect_mode(self) -> str:
        data = self.cmb_aspect.currentData()
        if data in ASPECT_MODES:
            return str(data)
        return self._aspect if self._aspect in ASPECT_MODES else ASPECT_PHYSICAL

    def set_aspect_mode(self, aspect: str) -> None:
        if aspect == "硬視窗":
            aspect = ASPECT_FILL
        if aspect not in ASPECT_MODES:
            aspect = ASPECT_PHYSICAL
        idx = self.cmb_aspect.findData(aspect)
        if idx >= 0:
            self.cmb_aspect.setCurrentIndex(idx)
        else:
            self._rebuild_aspect_combo(aspect)

    def language(self) -> str:
        return self._lang

    def set_language(self, lang: str) -> None:
        """Switch EN/中文 labels on axes, Aspect, footer / 切換軸標與 Aspect。"""
        lang = normalize_lang(lang)
        if lang == self._lang:
            return
        cur_aspect = self.aspect_mode()
        self._lang = lang
        self._rebuild_aspect_combo(cur_aspect)
        if self._rgb is not None:
            self._apply_pixmap()
            self._refresh_axes_caption()

    def show_axes(self) -> bool:
        return self.chk_axes.isChecked()

    def set_show_axes(self, on: bool) -> None:
        self.chk_axes.setChecked(bool(on))

    def focus_step_index(self) -> Optional[int]:
        return self._focus_step

    def set_focus_step(self, step: Optional[int]) -> None:
        """Update Focus-step marker (display only) / 更新步階標線（僅顯示）。"""
        self._focus_step = None if step is None else int(step)
        if self._rgb is not None:
            self._apply_pixmap()

    def set_save_meta(self, folder_name: str, roi_id: int) -> None:
        """Folder + ROI for Save Image default name / 另存預設檔名用。"""
        self._save_folder = str(folder_name or "TF")
        self._save_roi_id = int(roi_id)

    def default_save_basename(self) -> str:
        """``Folder_ROIX_Real|Pixel`` / 預設檔名（不含副檔名）。"""
        safe = re.sub(r'[<>:"/\\|?*\s]+', "_", self._save_folder).strip("._")
        if not safe:
            safe = "TF"
        kind = "Pixel" if self.aspect_mode() == ASPECT_FILL else "Real"
        return f"{safe}_ROI{self._save_roi_id}_{kind}"

    def _save_image_dialog(self) -> None:
        """Save composed TF PNG / 另存通焦合成 PNG。"""
        if self._rgb is None or self._last_map is None:
            QMessageBox.information(
                self, "Save Image",
                "No through-focus map yet — Analyze a ROI first.\n"
                "尚無通焦圖，請先對 ROI 執行 Analyze。")
            return
        default = self.default_save_basename() + ".png"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Through-Focus Image / 另存通焦圖",
            default, "PNG (*.png)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        if os.path.exists(path):
            QMessageBox.warning(
                self, "Save Image",
                "File exists; will not overwrite / 檔案已存在，不覆寫")
            return
        try:
            area = self.img_label.size()
            tw = max(int(area.width()), 640)
            th = max(int(area.height()), 480)
            pm = self._compose_frame(tw, th)
            if pm.isNull() or not pm.save(path, "PNG"):
                raise RuntimeError(f"QPixmap.save failed: {path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self, "Save Image",
                f"Save failed / 儲存失敗:\n{path}\n{exc}")
            return
        self.lbl_title.setText(f"Saved / 已儲存: {os.path.basename(path)}")

    def clear(self, message: str = "No ROI / 尚未選取 ROI") -> None:
        self._last_map = None
        self._rgb = None
        self._focus_step = None
        self.lbl_title.setText(message)
        self.lbl_axes.setText("")
        self.img_label.clear()
        self.img_label.setText(message)
        self.img_label.setStyleSheet(
            "background:#2a2a2a; border:1px solid #555; color:#aaa;")

    def show_map(self, tf_map: ThroughFocusMap) -> None:
        self._mode = self.mode()
        self._last_map = tf_map
        intensity = np.asarray(tf_map.intensity, dtype=np.float64)
        if intensity.ndim != 2 or intensity.size == 0:
            self.clear("Empty map / 通焦圖為空")
            self._last_map = tf_map
            return
        peak = float(np.nanmax(intensity))
        if not np.isfinite(peak) or peak <= 0:
            self.clear("No signal in ROI / ROI 內無訊號")
            self._last_map = tf_map
            return

        rgb, title = render_tf_image(tf_map, self._mode)
        # Flip vertically: focus[0] at bottom (Fig.2 Focus↑) /
        # 垂直翻轉：focus[0] 在下（Focus 向上）
        self._rgb = np.ascontiguousarray(np.flipud(rgb))
        self.img_label.setStyleSheet(
            "background:#111; border:1px solid #555;")
        self.img_label.setText("")
        self._apply_pixmap()
        self.lbl_title.setText(title)
        self._refresh_axes_caption()

    def _refresh_axes_caption(self) -> None:
        """Update footer: ranges + aspect mode note / 更新軸範圍與顯示模式註記。"""
        tf_map = self._last_map
        if tf_map is None:
            self.lbl_axes.setText("")
            return
        lang = self._lang
        unit = tf_map.unit
        r0, r1 = float(tf_map.radial[0]), float(tf_map.radial[-1])
        f0, f1 = float(tf_map.focus[0]), float(tf_map.focus[-1])
        phys = abs(f1 - f0) / max(abs(r1 - r0), 1e-12)
        norm_txt = (
            tr(lang, "peak_norm") if getattr(tf_map, "normalized", True)
            else tr(lang, "raw_intensity"))
        aspect = self.aspect_mode()
        if aspect == ASPECT_FILL:
            aspect_txt = (
                f"  {tr(lang, 'aspect_fill_cap')} "
                f"(phys H/W={_fmt_tick(phys)})")
        else:
            ratio, clamped = physical_hw_ratio(tf_map)
            cap = tr(lang, "aspect_physical_cap")
            if clamped:
                aspect_txt = (
                    f"  {cap} {tr(lang, 'aspect_clamped')} "
                    f"(phys H/W={_fmt_tick(phys)})")
            else:
                aspect_txt = f"  {cap} H/W={_fmt_tick(ratio)}"
        axes_txt = (
            f"  {tr(lang, 'axes_on')}" if self.show_axes()
            else f"  {tr(lang, 'axes_off')}")
        # Unit is shared for Radial and Focus / Radial 與 Focus 共用 Unit
        radial_lbl = tr(lang, "radial_axis", unit=unit)
        focus_lbl = tr(lang, "focus_axis", unit=unit)
        self.lbl_axes.setText(
            f"{radial_lbl}: {_fmt_tick(r0)} .. {_fmt_tick(r1)}    "
            f"{focus_lbl}: {_fmt_tick(f0)} .. {_fmt_tick(f1)} (↑)    "
            f"{norm_txt}{aspect_txt}{axes_txt}")

    def _compose_frame(self, canvas_w: int, canvas_h: int) -> QPixmap:
        """RGB + Focus/Radial ticks into one pixmap / 影像＋軸刻度合成。"""
        assert self._rgb is not None and self._last_map is not None
        return compose_tf_pixmap(
            self._rgb, self._last_map, self.aspect_mode(), canvas_w, canvas_h,
            show_axes=self.show_axes(),
            focus_step_index=self._focus_step,
            mode=self.mode(),
            lang=self._lang)

    def _apply_pixmap(self) -> None:
        if self._rgb is None or self._last_map is None:
            return
        area = self.img_label.size()
        tw = max(int(area.width()), 220)
        th = max(int(area.height()), 180)
        composed = self._compose_frame(tw, th)
        self.img_label.setPixmap(composed)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_pixmap()
