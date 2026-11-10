"""ThroughFocus_Viewer main window / ThroughFocus_Viewer 主視窗.

UI/UX per ReadMe (reference PSF ROI Editor; no reconstruction algorithms).
依 ReadMe：參考 PSF ROI Editor；不含重建演算法。
"""

from __future__ import annotations

import datetime as _dt
import os
import sys
import time
from pathlib import Path
from typing import List, Optional

import numpy as np
from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtGui import (
    QAction, QActionGroup, QColor, QCursor, QDesktopServices, QIcon,
    QKeySequence,
)
from shiboken6 import isValid
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
    QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QRadioButton, QSlider,
    QSplitter, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout,
    QWidget,
)

from viewer import __app_name__, __version__, app_logger
from viewer.gui.image_list import IMAGE_FILTER, FrameListPanel, ImageSession
from viewer.gui.image_view import (
    ImageView, apply_edge_mode, apply_false_color, to_display,
)
from viewer.gui.log_bridge import LogBridge, QtLogHandler
from viewer.path_display import safe_display_path
from viewer.gui.roi_item import (
    ROI_ROTA_MODES, ROI_ROTA_NONE, ROI_ROTA_UNIFIED, RoiItem,
)
from viewer.gui.tf_preview import (
    ASPECT_FILL, ASPECT_MODES, ASPECT_PHYSICAL, MODE_FALSE_COLOR,
    PREVIEW_MODES, TfPreviewPanel, export_tf_png_bytes,
)
from viewer.focus_align import snap_roi_to_focus_centroid
from viewer.image_io import (
    LoadedImage, expand_image_args, list_images_in_folder, load_image,
    path_isdir,
)
from viewer.profile import (
    LineProfile, extract_profile, extract_roi_intensity_2d,
)
from viewer.gui.excel_export_dialog import ExcelExportDialog
from viewer.result_export import (
    DefocusFramePatch, ExcelExportOptions, ExcelWorkbookWriter, ProfileSheet,
    ThroughFocusSheet, color_space_label, export_target_paths, format_level,
    roi_pixel_range,
)
from viewer.roi import RotatedRoi, normalize_angle_deg
from viewer.roi_settings import load_roi_settings, save_roi_settings
from viewer.tf_contour import (
    NA_MAX, NA_MIN, NA_NULL_SENTINEL, UNIT_NM, UNIT_UM, ScaleSettings,
    WN_MAX, WN_MIN, WN_NULL_SENTINEL,
    build_through_focus_map, format_na, format_wavenumber,
    normalize_na, normalize_wavenumber,
    unit_to_um_factor, um_to_unit_factor,
)
from viewer.tf_stack import folder_as_stack, group_paths_into_stacks
from viewer.ui_lang import (
    LANG_EN, LANG_LABELS, LANG_MODES, normalize_lang, tr,
)

COLORS = ["#ff3030", "#00c000", "#1f77ff", "#ff9900", "#c000c0",
          "#00b0b0", "#e0e000", "#8c564b", "#e377c2", "#7f7f7f"]
RESULT_COLUMNS = ["ROI_ID", "CX", "CY", "W", "H", "Rota_Angle",
                  "ColorSpace", "Max", "Min", "CalcTime", "FolderName"]
DEFAULT_ROI_SIZE = (40.0, 80.0)
def _app_root() -> Path:
    """Install / package root (next to Help HTML and optional Sample).

    安裝／打包根目錄（Help HTML 與可選 Sample 同層）。
    Frozen (PyInstaller): folder of the .exe. Dev: 99_Python/.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


_APP_ROOT = _app_root()
HELP_HTML = _APP_ROOT / "ThroughFocus_Viewer_Help.html"
# Window / taskbar icon (ico preferred, png fallback) /
# 視窗／工作列圖示（優先 ico，其次 png）
APP_ICON = _APP_ROOT / "assets" / "ThroughFocus_Viewer.ico"
APP_ICON_PNG = _APP_ROOT / "assets" / "ThroughFocus_Viewer.png"
# Root ReadMe.html stays as internal planning doc; Help menu opens HELP_HTML only.
README_HTML = (
    Path(__file__).resolve().parents[4] / "ReadMe.html"
    if not getattr(sys, "frozen", False)
    else HELP_HTML
)


def _load_app_icon() -> Optional[QIcon]:
    """Load branded app icon if present / 載入品牌圖示（若存在）。"""
    for path in (APP_ICON, APP_ICON_PNG):
        if path.is_file():
            return QIcon(str(path))
    return None
# Default Open Folder when launched with no args / 無參數啟動時預設開啟的資料夾
# Prefer SamplePicture/ (public demo) then Sample/ (legacy / local).
# 優先 SamplePicture/（公開示範），其次 Sample/（舊名／本機）。
def _default_open_folder() -> Path:
    for name in ("SamplePicture", "Sample"):
        candidate = _APP_ROOT / name
        if candidate.is_dir():
            return candidate
    return _APP_ROOT / "SamplePicture"


DEFAULT_OPEN_FOLDER = _default_open_folder()


class MainWindow(QMainWindow):
    """ThroughFocus_Viewer window / ThroughFocus_Viewer 視窗。"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{__app_name__} v{__version__} / ROI 框選")
        icon = _load_app_icon()
        if icon is not None and not icon.isNull():
            self.setWindowIcon(icon)
        self.resize(1280, 820)
        self.setAcceptDrops(True)
        self.log = app_logger.get_app_logger()
        self._bridge = LogBridge()
        self._bridge.message.connect(self._append_log)
        self._handler = QtLogHandler(self._bridge)
        self.log.addHandler(self._handler)
        self.sessions: List[ImageSession] = []
        self.current_si = -1
        self.items: List[RoiItem] = []
        self._updating = False
        self._activating = False
        self._step_updating = False
        self._frames_built_for = -1
        self._active_roi_id: Optional[int] = None
        self._scale_unit = UNIT_UM
        self._ui_lang = LANG_EN
        self._excel_busy = False
        self._progress_pump_t = 0.0
        self._build_ui()
        self._build_menus()
        self._restore_settings()
        self.log.info("%s v%s ready / 就緒", __app_name__, __version__)

    # ----- UI -----
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)

        self.view = ImageView()
        self.view.roi_drawn.connect(self._on_roi_drawn)
        self.view.cursor_moved.connect(self._on_cursor)
        self.view.draw_mode = True

        self.frames = FrameListPanel()
        self.frames.frame_activated.connect(self._activate_session)
        self.tf_preview = TfPreviewPanel()

        # Scale + Auto/Manual (shared unit for X/Y/Z) /
        # 尺度與 Auto／Manual（X／Y／Z 共用單位）
        scale_row = QHBoxLayout()
        self.radio_auto = QRadioButton("Auto")
        self.radio_manual = QRadioButton("Manual")
        self.radio_auto.setChecked(True)
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self.radio_auto)
        self._mode_group.addButton(self.radio_manual)
        scale_row.addWidget(self.radio_auto)
        scale_row.addWidget(self.radio_manual)
        self.btn_analyze = QPushButton("Analyze")
        self.btn_analyze.setToolTip(
            "Build through-focus contour for selected ROI / "
            "對選取 ROI 產生通焦等高線")
        self.btn_analyze.clicked.connect(self.analyze_through_focus)
        scale_row.addWidget(self.btn_analyze)
        self.chk_normalize = QCheckBox("Normalize")
        self.chk_normalize.setChecked(True)
        self.chk_normalize.setToolTip(
            "Peak-normalise through-focus intensity (Fig.2 style); "
            "off = raw intensity for preview/Excel\n"
            "通焦強度峰值歸一（仿 Fig.2）；關閉＝原始強度（預覽／Excel）")
        self.chk_normalize.toggled.connect(self._on_scale_changed)
        scale_row.addWidget(self.chk_normalize)
        scale_row.addWidget(QLabel("X_Pixel"))
        self.sp_x_pixel = QDoubleSpinBox()
        self.sp_x_pixel.setDecimals(6)
        self.sp_x_pixel.setRange(1e-9, 1e6)
        self.sp_x_pixel.setValue(1.0)
        self.sp_x_pixel.setMaximumWidth(90)
        self.sp_x_pixel.valueChanged.connect(self._on_scale_changed)
        scale_row.addWidget(self.sp_x_pixel)
        scale_row.addWidget(QLabel("Y_Pixel"))
        self.sp_y_pixel = QDoubleSpinBox()
        self.sp_y_pixel.setDecimals(6)
        self.sp_y_pixel.setRange(1e-9, 1e6)
        self.sp_y_pixel.setValue(1.0)
        self.sp_y_pixel.setMaximumWidth(90)
        self.sp_y_pixel.valueChanged.connect(self._on_scale_changed)
        scale_row.addWidget(self.sp_y_pixel)
        scale_row.addWidget(QLabel("Z_Step"))
        self.sp_z_step = QDoubleSpinBox()
        self.sp_z_step.setDecimals(6)
        self.sp_z_step.setRange(1e-9, 1e6)
        self.sp_z_step.setValue(1.0)
        self.sp_z_step.setMaximumWidth(90)
        self.sp_z_step.valueChanged.connect(self._on_scale_changed)
        scale_row.addWidget(self.sp_z_step)
        # Order: … Z_Step | Wavenumber | Unit | NA | …
        # 順序：… Z_Step | Wavenumber | Unit | NA | …
        scale_row.addWidget(QLabel("Wavenumber"))
        self.sp_wavenumber = QDoubleSpinBox()
        self.sp_wavenumber.setDecimals(8)
        self.sp_wavenumber.setRange(WN_NULL_SENTINEL, WN_MAX)
        self.sp_wavenumber.setSpecialValueText("NULL")
        self.sp_wavenumber.setSingleStep(0.01)
        self.sp_wavenumber.setValue(WN_NULL_SENTINEL)
        self.sp_wavenumber.setMaximumWidth(110)
        self.sp_wavenumber.setToolTip(
            "Wavenumber: NULL (unset) or 0.00000001～1e6 "
            "(metadata; not converted by Unit)\n"
            "Wavenumber：NULL（未填）或 0.00000001～1e6"
            "（記錄用；不隨 Unit 換算）")
        self.sp_wavenumber.editingFinished.connect(self._clamp_wavenumber_spin)
        self.sp_wavenumber.valueChanged.connect(self._on_wavenumber_spin_changed)
        scale_row.addWidget(self.sp_wavenumber)
        self.lbl_unit = QLabel("Unit")
        scale_row.addWidget(self.lbl_unit)
        self.cmb_unit = QComboBox()
        self.cmb_unit.addItems([UNIT_UM, UNIT_NM])
        self.cmb_unit.setToolTip(
            "Shared unit for X_Pixel, Y_Pixel, Z_Step and TF axes. "
            "Switching µm↔nm converts spin values (physical size kept).\n"
            "X／Y／Z 與通焦軸共用單位；µm↔nm 時會換算數值（物理尺寸不變）。")
        self.cmb_unit.currentTextChanged.connect(self._on_unit_changed)
        scale_row.addWidget(self.cmb_unit)
        scale_row.addWidget(QLabel("NA"))
        self.sp_na = QDoubleSpinBox()
        self.sp_na.setDecimals(8)
        # Minimum = NULL (specialValueText); real values [1e-8, 2.0]
        # 最小值＝NULL；有效值 [1e-8, 2.0]
        self.sp_na.setRange(NA_NULL_SENTINEL, NA_MAX)
        self.sp_na.setSpecialValueText("NULL")
        self.sp_na.setSingleStep(0.01)
        self.sp_na.setValue(NA_NULL_SENTINEL)
        self.sp_na.setMaximumWidth(100)
        self.sp_na.setToolTip(
            "NA: NULL (unset) or 0.00000001～2.0 (dimensionless; "
            "not converted by Unit)\n"
            "NA：NULL（未填）或 0.00000001～2.0（無單位；不隨 Unit 換算）")
        self.sp_na.editingFinished.connect(self._clamp_na_spin)
        self.sp_na.valueChanged.connect(self._on_na_spin_changed)
        scale_row.addWidget(self.sp_na)
        self.chk_false_color = QCheckBox("False Color")
        self.chk_false_color.setToolTip(
            "Preview: turbo false-color on main image / "
            "主圖 Preview：turbo 偽彩（僅顯示）")
        self.chk_false_color.toggled.connect(self._on_preview_mode_toggled)
        scale_row.addWidget(self.chk_false_color)
        self.chk_edge = QCheckBox("Edge")
        self.chk_edge.setToolTip(
            "Preview: gradient-magnitude edge map on main image / "
            "主圖 Preview：梯度邊緣圖（僅顯示；與 False Color 互斥）")
        self.chk_edge.toggled.connect(self._on_preview_mode_toggled)
        scale_row.addWidget(self.chk_edge)
        scale_row.addWidget(QLabel("ROI_Rota"))
        self.cmb_roi_rota = QComboBox()
        self.cmb_roi_rota.addItems(list(ROI_ROTA_MODES))
        self.cmb_roi_rota.setCurrentText(ROI_ROTA_NONE)
        self.cmb_roi_rota.setToolTip(
            "向心＝ROI 內朝影像中心虛線；統一旋轉＝R／Angle 全 ROI 同轉；"
            "None＝關閉\n"
            "向心 = dashed axis toward image centre (inside ROI); "
            "統一旋轉 = R/Angle rotates all ROIs; None = off")
        self.cmb_roi_rota.currentTextChanged.connect(self._on_roi_rota_changed)
        scale_row.addWidget(self.cmb_roi_rota)
        scale_row.addStretch(1)
        scale_w = QWidget()
        scale_w.setLayout(scale_row)

        # Focus step bar under the image / 影像下方的通焦步階列
        step_row = QHBoxLayout()
        step_row.addWidget(QLabel("Focus step"))
        self.slider_step = QSlider(Qt.Orientation.Horizontal)
        self.slider_step.setMinimum(0)
        self.slider_step.setMaximum(0)
        self.slider_step.setEnabled(False)
        self.slider_step.valueChanged.connect(self._on_step_slider)
        step_row.addWidget(self.slider_step, 1)
        self.lbl_step = QLabel("step —")
        self.lbl_step.setMinimumWidth(160)
        step_row.addWidget(self.lbl_step)
        step_w = QWidget()
        step_w.setLayout(step_row)

        # Scale bar above image (left) / 尺度列放在左側影像上方
        view_col = QWidget()
        vc = QVBoxLayout(view_col)
        vc.setContentsMargins(0, 0, 0, 0)
        vc.setSpacing(4)
        vc.addWidget(scale_w)
        vc.addWidget(self.view, 1)
        vc.addWidget(step_w)

        edit = QHBoxLayout()
        self.chk_draw = QCheckBox("Draw mode (D)")
        self.chk_draw.setChecked(True)
        self.chk_draw.toggled.connect(self._toggle_draw)
        self.chk_fixed = QCheckBox("Fixed size")
        self.chk_fixed.toggled.connect(self._toggle_fixed)
        self.chk_snap_centroid = QCheckBox("Snap to focus centroid")
        self.chk_snap_centroid.setToolTip(
            "Auto-align ROI centre to intensity centroid on the in-focus "
            "frame (dz≈0) / 自動將 ROI 中心對齊合焦幀（dz≈0）強度質心")
        self.chk_snap_centroid.toggled.connect(self._on_snap_centroid_toggled)
        edit.addWidget(self.chk_draw)
        edit.addWidget(self.chk_fixed)
        edit.addWidget(self.chk_snap_centroid)
        self.sp_cx = self._spin("CX", edit, self._apply_spin)
        self.sp_cy = self._spin("CY", edit, self._apply_spin)
        self.sp_w = self._spin("W", edit, self._apply_spin, 1.0, 10000.0)
        self.sp_h = self._spin("H", edit, self._apply_spin, 1.0, 10000.0)
        self.sp_ang = self._spin("Angle", edit, self._apply_spin, -90.0, 90.0)
        btn_del = QPushButton("Delete ROI")
        btn_del.clicked.connect(self._delete_selected)
        edit.addWidget(btn_del)
        edit.addStretch(1)

        self.table = QTableWidget(0, len(RESULT_COLUMNS))
        self.table.setHorizontalHeaderLabels(RESULT_COLUMNS)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.itemSelectionChanged.connect(self._on_table_select)

        self.log_panel = QPlainTextEdit()
        self.log_panel.setReadOnly(True)
        self.log_panel.setMaximumBlockCount(2000)
        self.log_wrap = QWidget()
        ll = QVBoxLayout(self.log_wrap)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("<b>Log / 日誌</b>"))
        ll.addWidget(self.log_panel)

        result_wrap = QWidget()
        rl = QVBoxLayout(result_wrap)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel("<b>Result</b>"))
        rl.addWidget(self.table)

        # All splitters are user-draggable / 各分割條皆可拖拉調整
        self.log_split = QSplitter(Qt.Orientation.Horizontal)
        self.log_split.addWidget(result_wrap)
        self.log_split.addWidget(self.log_wrap)
        self.log_split.setChildrenCollapsible(True)
        self.log_split.setStretchFactor(0, 3)
        self.log_split.setStretchFactor(1, 2)
        self.log_split.setSizes([700, 460])
        result_wrap.setMinimumWidth(120)
        self.log_wrap.setMinimumWidth(100)

        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addLayout(edit)
        bl.addWidget(self.log_split, 1)
        bottom.setMinimumHeight(80)
        view_col.setMinimumHeight(80)

        # PSF-style: left = view|bottom ; right = Groups|TF preview
        # PSF 式：左側 = 影像|下方；右側 = 圖集|通焦預覽
        self.left_split = QSplitter(Qt.Orientation.Vertical)
        self.left_split.addWidget(view_col)
        self.left_split.addWidget(bottom)
        self.left_split.setChildrenCollapsible(True)
        self.left_split.setStretchFactor(0, 1)
        self.left_split.setStretchFactor(1, 1)
        self.left_split.setSizes([560, 320])

        self.groups_split = QSplitter(Qt.Orientation.Vertical)
        self.groups_split.addWidget(self.frames)
        self.groups_split.addWidget(self.tf_preview)
        # Keep TF preview visible (do not collapse to zero) /
        # 通焦預覽不可收成零高度
        self.groups_split.setChildrenCollapsible(False)
        self.frames.setMinimumHeight(80)
        self.tf_preview.setMinimumHeight(260)
        self.groups_split.setStretchFactor(0, 1)
        self.groups_split.setStretchFactor(1, 2)
        self.groups_split.setSizes([240, 360])

        right_col = QWidget()
        rc = QVBoxLayout(right_col)
        rc.setContentsMargins(0, 0, 0, 0)
        rc.setSpacing(4)
        rc.addWidget(self.groups_split, 1)
        # Wide enough for Mode / Aspect without overlap /
        # 右側夠寬，Mode／Aspect 才不會擠疊
        right_col.setMinimumWidth(300)

        self.body_split = QSplitter(Qt.Orientation.Horizontal)
        self.body_split.addWidget(self.left_split)
        self.body_split.addWidget(right_col)
        self.body_split.setChildrenCollapsible(True)
        self.body_split.setHandleWidth(6)
        # Both sides grow with window; keep TF pane draggable /
        # 左右隨視窗等比伸縮，通焦側可橫向拖移
        self.body_split.setStretchFactor(0, 3)
        self.body_split.setStretchFactor(1, 2)
        self.body_split.setSizes([900, 420])
        root.addWidget(self.body_split, 1)

        self.status = self.statusBar()
        self._status_path = QLabel("Process: No image / 尚未開啟影像")
        self.status.addWidget(self._status_path, 1)
        self.progress = QProgressBar()
        self.progress.setMinimumWidth(260)
        self.progress.setMaximumWidth(360)
        self._reset_progress()
        self.status.addPermanentWidget(self.progress)
        self.btn_log = QToolButton()
        self.btn_log.setText("Log")
        self.btn_log.setCheckable(True)
        self.btn_log.setChecked(True)
        self.btn_log.setAutoRaise(True)
        self.btn_log.setToolTip("Show / hide Log (Ctrl+L) / 顯示／隱藏日誌")
        self.btn_log.clicked.connect(self._toggle_log)
        self.status.addPermanentWidget(self.btn_log)
        self._status_xy = QLabel("")
        self.status.addPermanentWidget(self._status_xy)

    def _reset_progress(self) -> None:
        """Idle progress bar / 進度列回到待命。"""
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setFormat("Idle / 待命")

    def _set_progress(self, value: int, maximum: int, text: str,
                      *, force: bool = False) -> None:
        """Update progress; throttle processEvents to avoid UI stutter.

        更新進度；節流 processEvents，避免 Excel 匯出時卡卡卡。
        """
        maximum = max(int(maximum), 1)
        value = max(0, min(int(value), maximum))
        self.progress.setRange(0, maximum)
        self.progress.setValue(value)
        self.progress.setFormat(text)
        now = time.monotonic()
        # ~8 Hz pump; force on start/end / 約每秒 8 次；起迄強制刷新
        if force or (now - self._progress_pump_t) >= 0.125:
            self._progress_pump_t = now
            QApplication.processEvents()

    def _spin(self, label: str, lay: QHBoxLayout, slot, lo=-1e6, hi=1e6
              ) -> QDoubleSpinBox:
        lay.addWidget(QLabel(label))
        sp = QDoubleSpinBox()
        sp.setDecimals(3)
        sp.setRange(lo, hi)
        sp.setMaximumWidth(100)
        sp.valueChanged.connect(slot)
        lay.addWidget(sp)
        return sp

    def _build_menus(self) -> None:
        mb = self.menuBar()
        m_file = mb.addMenu("File")
        self._act(m_file, "Open Image(s)... / 開啟影像（可多選）",
                  self.open_images, QKeySequence.StandardKey.Open)
        self._act(m_file, "Open Folder... / 開啟資料夾（一個圖集 Group）",
                  self.open_folder, "Ctrl+Shift+O")
        self.act_export_excel = self._act(
            m_file, "Export Excel... / 匯出 Excel",
            self.export_excel, "Ctrl+E")
        m_file.addSeparator()
        self._act(m_file, "Save ROI Settings... / ROI 設定另存",
                  self.save_roi_settings_dialog, "Ctrl+S")
        self._act(m_file, "Load ROI Settings... / 載入 ROI 設定",
                  self.load_roi_settings_dialog, "Ctrl+Shift+S")
        m_file.addSeparator()
        self._act(m_file, "Exit / 結束", self.close, QKeySequence.StandardKey.Quit)

        m_edit = mb.addMenu("Edit")
        self._act(m_edit, "Delete Selected ROI / 刪除選取 ROI",
                  self._delete_selected, QKeySequence.StandardKey.Delete)
        self._act(m_edit, "Rotate 90 deg / 旋轉 90 度", self._rotate_90, "R")

        m_view = mb.addMenu("View")
        self._act(m_view, "Fit Image / 符合視窗", lambda: self.view.fit(), "F")
        self.act_log = self._act(
            m_view, "Show Log Panel / 顯示 Log 面板",
            self._toggle_log, "Ctrl+L", checkable=True)
        self.act_log.setChecked(True)
        self._act(m_view, "Previous Focus Step / 上一通焦步階",
                  self._prev_step, "[")
        self._act(m_view, "Next Focus Step / 下一通焦步階",
                  self._next_step, "]")

        # Lang between View and Help / Lang 在 View 與 Help 之間
        self.m_lang = mb.addMenu("Lang")
        self.m_lang.setToolTip(
            "UI language for TF axes / Aspect / footer "
            "(menus stay bilingual)\n"
            "通焦軸標、Aspect、頁腳語言（選單仍中英並列）")
        self._lang_group = QActionGroup(self)
        self._lang_group.setExclusive(True)
        self._lang_actions = {}
        for code in LANG_MODES:
            act = QAction(LANG_LABELS[code], self)
            act.setCheckable(True)
            act.setData(code)
            if code == LANG_EN:
                act.setChecked(True)
            self._lang_group.addAction(act)
            self.m_lang.addAction(act)
            self._lang_actions[code] = act
        self._lang_group.triggered.connect(self._on_lang_action)

        m_help = mb.addMenu("Help")
        self._act(m_help, "Help / 說明", self.open_help, "F1")
        self._act(m_help, "Release Notes / 版本紀錄", self.open_release)
        self._act(m_help, "Usage / 使用摘要", self.open_usage)

    def _act(self, menu, text, slot, shortcut=None, checkable=False) -> QAction:
        a = QAction(text, self)
        if shortcut is not None:
            a.setShortcut(shortcut if isinstance(shortcut, QKeySequence)
                          else QKeySequence(shortcut))
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        menu.addAction(a)
        return a

    # ----- sessions / images -----
    def open_images(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open Image(s)", "", IMAGE_FILTER)
        if paths:
            self.load_paths(paths)

    def open_folder(self) -> None:
        """Open one folder as a single Frames group / 開啟資料夾並建成一個 group。"""
        folder = QFileDialog.getExistingDirectory(
            self, "Open Folder / 開啟資料夾（一個圖集 Group）")
        if folder:
            self.load_paths([folder])

    def load_paths(self, args: List[str]) -> None:
        """Load folders as one Frames group each; loose files use TF grouping.

        每個資料夾在 Frames 建成一個 group／圖集；散檔仍依 TF Field 分組。
        """
        folders: List[str] = []
        file_args: List[str] = []
        for arg in args:
            arg = arg.strip().strip('"')
            if not arg:
                continue
            if path_isdir(arg):
                folders.append(os.path.abspath(arg))
            else:
                file_args.append(arg)

        stacks = []
        for folder in folders:
            paths, reason = list_images_in_folder(folder)
            if reason:
                self.log.warning(
                    "Skip %s: %s", safe_display_path(folder), reason)
                continue
            stacks.append(folder_as_stack(folder, paths))

        if file_args:
            paths, skipped = expand_image_args(file_args)
            for arg, reason in skipped:
                self.log.warning(
                    "Skip %s: %s", safe_display_path(arg), reason)
            if paths:
                stacks.extend(group_paths_into_stacks(paths))

        if not stacks:
            self.log.warning("No images loaded / 未載入影像")
            return

        first_new = len(self.sessions)
        self._frames_built_for = -1
        for label, stack_paths, metas in stacks:
            self._append_stack(label, stack_paths, metas)
        if self.sessions:
            self._activate_session(first_new if first_new < len(self.sessions)
                                   else len(self.sessions) - 1)

    def _append_stack(self, label: str, stack_paths: List[str], metas) -> None:
        """Load paths into one ImageSession / 載入路徑成為一個 ImageSession。"""
        frames: List[LoadedImage] = []
        displays = []
        ok_metas = []
        for p, meta in zip(stack_paths, metas):
            try:
                img = load_image(p)
            except Exception as exc:  # noqa: BLE001
                self.log.error(
                    "Load failed %s: %s", safe_display_path(p), exc)
                continue
            if img.raw.ndim == 3 and img.raw.shape[2] >= 3:
                disp = to_display(img.raw[..., :3])
            else:
                disp = to_display(img.luminance)
            frames.append(img)
            displays.append(disp)
            ok_metas.append(meta)
            self.log.info("Opened / 已開啟: %s (%dx%d)",
                          safe_display_path(p), img.width, img.height)
        if not frames:
            return
        # Prefer mid-focus step when available / 有中間焦點時預設選中
        mid = 0
        for i, m in enumerate(ok_metas):
            if m is not None and abs(m.dz_mm) < 1e-9:
                mid = i
                break
        else:
            mid = len(frames) // 2
        self.sessions.append(ImageSession(
            frames=frames, displays=displays, metas=ok_metas,
            label=label, current_step=mid, rois=[]))
        self.log.info("Group / 圖集: %s (%d frames)", label, len(frames))

    def _activate_session(self, si: int) -> None:
        if si < 0 or si >= len(self.sessions):
            return
        if self._activating:
            return
        self._activating = True
        try:
            prefer_id = self._active_roi_id
            sel = self._selected_item()
            if sel is not None:
                prefer_id = sel.roi.roi_id
            self._save_current_rois()
            self.current_si = si
            sess = self.sessions[si]
            self._rebuild_session_view(sess, fit=True, prefer_roi_id=prefer_id)
            if self._frames_built_for != len(self.sessions):
                self.frames.set_sessions(self.sessions, current=si)
                self._frames_built_for = len(self.sessions)
            else:
                self.frames.select_session(si)
            self._sync_step_controls(sess)
            self._refresh_table()
            # No absolute/user path in status (PII) / 狀態列不顯示路徑個資
            self._status_path.setText(
                f"Process: {sess.image.width}x{sess.image.height}")
        finally:
            self._activating = False
        self._maybe_auto_analyze()

    def _rebuild_session_view(
        self,
        sess: ImageSession,
        fit: bool = False,
        prefer_roi_id: Optional[int] = None,
    ) -> None:
        """Load session image and recreate ROI items (set_image clears scene).

        載入影像並重建 ROI（set_image 會清空場景，不可再 remove 舊 item）。
        """
        # Drop Python refs; scene.clear() inside set_image deletes C++ items.
        # 丟掉 Python 參考；set_image 內的 scene.clear() 會刪掉 C++ 物件。
        self.items.clear()
        self.view.set_image(self._display_for_view(sess.display))
        if fit:
            self.view.fit()
        for roi in sess.rois:
            self._add_item(roi, select=False)
        self._select_roi_id(prefer_roi_id)

    def _select_roi_id(self, roi_id: Optional[int]) -> None:
        """Select ROI by id, else first item / 依 id 選 ROI，否則選第一個。"""
        self._prune_dead_items()
        if not self.items:
            self._active_roi_id = None
            return
        target = None
        if roi_id is not None:
            for it in self.items:
                if it.roi.roi_id == roi_id:
                    target = it
                    break
        if target is None:
            target = self.items[0]
        self.view.scene().clearSelection()
        target.setSelected(True)
        self._active_roi_id = target.roi.roi_id
        self._fill_spins(target.roi)

    def _prune_dead_items(self) -> None:
        """Removes invalid RoiItem wrappers / 移除已刪除的 RoiItem 包裝。"""
        self.items = [it for it in self.items if isValid(it)]

    def _sync_step_controls(self, sess: ImageSession) -> None:
        self._step_updating = True
        n = sess.n_steps
        self.slider_step.setEnabled(n > 1)
        self.slider_step.setMaximum(max(0, n - 1))
        self.slider_step.setValue(sess.current_step)
        self.lbl_step.setText(sess.step_label())
        self.tf_preview.set_focus_step(sess.current_step)
        self._step_updating = False

    def _on_step_slider(self, value: int) -> None:
        if self._step_updating:
            return
        self._set_session_step(value)

    def _prev_step(self) -> None:
        sess = self._session()
        if sess is None:
            return
        self._set_session_step(sess.current_step - 1)

    def _next_step(self) -> None:
        sess = self._session()
        if sess is None:
            return
        self._set_session_step(sess.current_step + 1)

    def _set_session_step(self, step: int) -> None:
        """Change focus plane only; keep ROI graphics / 只換焦面，保留 ROI。"""
        sess = self._session()
        if sess is None:
            return
        self._save_current_rois()
        if not sess.set_step(step):
            return
        # replace_image keeps RoiItems; set_image would wipe them.
        # replace_image 保留 ROI；set_image 會清掉。
        self.view.replace_image(self._display_for_view(sess.display), fit=False)
        self._sync_step_controls(sess)
        # TF marker follows Focus step (display only) / 通焦標線跟隨步階（僅顯示）
        self.tf_preview.set_focus_step(sess.current_step)
        self.frames.update_session_row(self.current_si)
        self._refresh_table()
        self._status_path.setText(
            f"Process: {sess.image.width}x{sess.image.height}")

    def _save_current_rois(self) -> None:
        self._prune_dead_items()
        if 0 <= self.current_si < len(self.sessions):
            self.sessions[self.current_si].rois = [
                it.roi for it in self.items if isValid(it)]

    def _session(self) -> Optional[ImageSession]:
        if 0 <= self.current_si < len(self.sessions):
            return self.sessions[self.current_si]
        return None

    def _image(self) -> Optional[LoadedImage]:
        s = self._session()
        return s.image if s else None

    def _display_for_view(self, display) -> np.ndarray:
        """Preview modes on main image / 主圖 Preview 顯示模式。"""
        if self.chk_edge.isChecked():
            return apply_edge_mode(display)
        if self.chk_false_color.isChecked():
            return apply_false_color(display)
        return display

    def _on_preview_mode_toggled(self, checked: bool = False) -> None:
        """False Color / Edge are exclusive on Preview / 主圖兩者互斥。"""
        sender = self.sender()
        if checked and sender is self.chk_edge and self.chk_false_color.isChecked():
            self.chk_false_color.blockSignals(True)
            self.chk_false_color.setChecked(False)
            self.chk_false_color.blockSignals(False)
        elif checked and sender is self.chk_false_color and self.chk_edge.isChecked():
            self.chk_edge.blockSignals(True)
            self.chk_edge.setChecked(False)
            self.chk_edge.blockSignals(False)
        sess = self._session()
        if sess is None:
            return
        self.view.replace_image(self._display_for_view(sess.display), fit=False)

    # ----- ROI -----
    def _on_roi_drawn(self, rect) -> None:
        img = self._image()
        if img is None:
            return
        cx = rect.x() + rect.width() / 2.0
        cy = rect.y() + rect.height() / 2.0
        w = max(rect.width(), 1.0)
        h = max(rect.height(), 1.0)
        if self.chk_fixed.isChecked():
            w, h = self.sp_w.value() or DEFAULT_ROI_SIZE[0], self.sp_h.value() or DEFAULT_ROI_SIZE[1]
            if w < 1:
                w = DEFAULT_ROI_SIZE[0]
            if h < 1:
                h = DEFAULT_ROI_SIZE[1]
        rid = max((it.roi.roi_id for it in self.items), default=0) + 1
        roi = RotatedRoi(cx=cx, cy=cy, dx=w, dy=h, angle_deg=0.0, roi_id=rid)
        item = self._add_item(roi, select=True)
        if self.chk_snap_centroid.isChecked():
            self._snap_item_to_focus_centroid(item, jump_step=True)
        self._refresh_table()
        self.log.info("ROI %d added / 新增 ROI %d", rid, rid)
        self._maybe_auto_analyze()

    def _add_item(self, roi: RotatedRoi, select: bool = True) -> RoiItem:
        color = QColor(COLORS[(roi.roi_id - 1) % len(COLORS)])
        item = RoiItem(roi, color, on_changed=self._on_roi_changed)
        item.set_fixed_size(self.chk_fixed.isChecked())
        item.set_rota_mode(self.cmb_roi_rota.currentText())
        img = self._image()
        if img is not None:
            item.set_image_size(float(img.width), float(img.height))
        self.view.scene().addItem(item)
        self.items.append(item)
        if select:
            self.view.scene().clearSelection()
            item.setSelected(True)
            self._active_roi_id = roi.roi_id
            self._fill_spins(roi)
        return item

    def _sync_roi_image_sizes(self) -> None:
        """Push current image size to all ROI items / 把影像尺寸同步到所有 ROI。"""
        img = self._image()
        if img is None:
            return
        w, h = float(img.width), float(img.height)
        for it in self.items:
            if isValid(it):
                it.set_image_size(w, h)

    def _on_roi_rota_changed(self, mode: str = "") -> None:
        """Apply Preview ROI_Rota mode to all items / 套用 Preview ROI_Rota 到全部 ROI。"""
        mode = mode or self.cmb_roi_rota.currentText()
        if mode not in ROI_ROTA_MODES:
            mode = ROI_ROTA_NONE
            self.cmb_roi_rota.blockSignals(True)
            self.cmb_roi_rota.setCurrentText(mode)
            self.cmb_roi_rota.blockSignals(False)
        self._prune_dead_items()
        for it in self.items:
            if isValid(it):
                it.set_rota_mode(mode)

    def _roi_rota_unified(self) -> bool:
        return self.cmb_roi_rota.currentText() == ROI_ROTA_UNIFIED

    def _on_roi_changed(self, item: RoiItem, final: bool) -> None:
        if not isValid(item):
            return
        if item.isSelected():
            self._active_roi_id = item.roi.roi_id
            self._fill_spins(item.roi)
        if final:
            if self.chk_snap_centroid.isChecked():
                self._snap_item_to_focus_centroid(item, jump_step=False)
            self._refresh_table()
            self._maybe_auto_analyze()

    def _selected_item(self) -> Optional[RoiItem]:
        """Selected ROI, or last active / first; skips deleted wrappers.

        選取中的 ROI，或上次／第一個；略過已刪除的包裝。
        """
        self._prune_dead_items()
        for it in self.items:
            if it.isSelected():
                self._active_roi_id = it.roi.roi_id
                return it
        if self._active_roi_id is not None:
            for it in self.items:
                if it.roi.roi_id == self._active_roi_id:
                    return it
        return self.items[0] if self.items else None

    def _fill_spins(self, roi: RotatedRoi) -> None:
        self._updating = True
        self.sp_cx.setValue(roi.cx)
        self.sp_cy.setValue(roi.cy)
        self.sp_w.setValue(roi.w)
        self.sp_h.setValue(roi.h)
        self.sp_ang.setValue(roi.angle_deg)
        self._updating = False

    def _apply_spin(self, *_args) -> None:
        if self._updating:
            return
        item = self._selected_item()
        if item is None:
            return
        old_ang = float(item.roi.angle_deg)
        item.roi.cx = self.sp_cx.value()
        item.roi.cy = self.sp_cy.value()
        item.roi.dx = max(self.sp_w.value(), 1.0)
        item.roi.dy = max(self.sp_h.value(), 1.0)
        new_ang = normalize_angle_deg(self.sp_ang.value())
        delta = new_ang - old_ang
        if abs(delta) > 1e-12 and self._roi_rota_unified():
            # 統一旋轉：所有 ROI 同一角度增量
            self._rotate_all_by(delta)
        else:
            item.roi.angle_deg = new_ang
            item.sync_from_roi()
        self._refresh_table()
        self._maybe_auto_analyze()

    def _delete_selected(self) -> None:
        """Delete selected ROI(s) without crashing on the first / only item.

        刪除選取 ROI（含刪第一個／唯一一個）時阻斷 scene 訊號，避免對已銷毀
        wrapper 再呼叫 isSelected／analyze。
        """
        self._prune_dead_items()
        sel = [it for it in self.items if isValid(it) and it.isSelected()]
        if not sel:
            return
        deleted_ids = {int(it.roi.roi_id) for it in sel}
        n_del = len(sel)
        self._activating = True
        scene = self.view.scene()
        try:
            scene.blockSignals(True)
            try:
                for it in list(sel):
                    if it in self.items:
                        self.items.remove(it)
                    if isValid(it):
                        scene.removeItem(it)
            finally:
                scene.blockSignals(False)
            if self._active_roi_id in deleted_ids:
                self._active_roi_id = None
            self._prune_dead_items()
            self._refresh_table()
            if self.items:
                scene.clearSelection()
                nxt = self.items[0]
                if isValid(nxt):
                    nxt.setSelected(True)
                    self._active_roi_id = nxt.roi.roi_id
                    self._fill_spins(nxt.roi)
            else:
                self.tf_preview.clear()
        finally:
            self._activating = False
        self.log.info("Deleted %d ROI(s) / 已刪除 %d 個 ROI", n_del, n_del)
        if self.items:
            self._maybe_auto_analyze()

    def _rotate_all_by(self, delta_deg: float) -> None:
        """Add ``delta_deg`` to every ROI angle / 所有 ROI 角度加上增量。"""
        self._prune_dead_items()
        for it in self.items:
            if not isValid(it):
                continue
            it.roi.angle_deg = normalize_angle_deg(it.roi.angle_deg + delta_deg)
            it.sync_from_roi()
        sel = self._selected_item()
        if sel is not None:
            self._fill_spins(sel.roi)

    def _rotate_90(self) -> None:
        """Rotate +90°: all ROIs if 統一旋轉, else selected only.

        +90°：ROI_Rota＝統一旋轉時全部聯動，否則只轉選取。
        """
        item = self._selected_item()
        if item is None and not self.items:
            return
        if self._roi_rota_unified():
            self._rotate_all_by(90.0)
            self.log.info("Rotated all ROIs +90° / 全部 ROI 旋轉 +90°")
        else:
            if item is None:
                return
            item.roi.angle_deg = normalize_angle_deg(item.roi.angle_deg + 90.0)
            item.sync_from_roi()
            self._fill_spins(item.roi)
            self.log.info(
                "Rotated ROI %d +90° / ROI %d 旋轉 +90°",
                item.roi.roi_id, item.roi.roi_id)
        self._refresh_table()
        self._maybe_auto_analyze()

    def _toggle_draw(self, on: bool) -> None:
        self.view.draw_mode = on

    def _toggle_fixed(self, on: bool) -> None:
        self.view.fixed_size = (self.sp_w.value(), self.sp_h.value()) if on else None
        self._prune_dead_items()
        for it in self.items:
            if isValid(it):
                it.set_fixed_size(on)

    def _toggle_log(self, on: bool = None) -> None:
        if isinstance(on, bool) and self.sender() in (self.act_log, self.btn_log):
            visible = bool(on)
        else:
            visible = not self.log_wrap.isVisible()
        self.log_wrap.setVisible(visible)
        self.act_log.blockSignals(True)
        self.act_log.setChecked(visible)
        self.act_log.blockSignals(False)
        self.btn_log.blockSignals(True)
        self.btn_log.setChecked(visible)
        self.btn_log.blockSignals(False)

    # ----- result table -----
    def _folder_name(self) -> str:
        """Group / parent folder name for Result / Result 用的圖集／資料夾名。"""
        sess = self._session()
        if sess is not None and sess.label:
            return str(sess.label)
        img = self._image()
        if img is None:
            return ""
        parent = os.path.basename(os.path.dirname(img.path))
        return parent or os.path.basename(img.path)

    def _roi_overlaps_image(self, roi: RotatedRoi) -> bool:
        """ROI has any coverage inside current image / ROI 是否與影像有交集。"""
        img = self._image()
        if img is None:
            return False
        return roi.overlaps_image(img.width, img.height)

    def _refresh_table(self) -> None:
        img = self._image()
        self.table.setRowCount(0)
        if img is None:
            return
        self._prune_dead_items()
        cs = color_space_label(img.bit_depth, img.channels)
        folder = self._folder_name()
        for it in self.items:
            if not isValid(it):
                continue
            roi = it.roi
            # Max/Min from in-image pixels only / Max／Min 只取影像內像素
            if roi.overlaps_image(img.width, img.height):
                rng = roi_pixel_range(img.luminance, roi)
                mx = format_level(rng[0]) if rng else ""
                mn = format_level(rng[1]) if rng else ""
                calc = roi.meta.get("calc_time_s")
                calc_txt = f"{float(calc):.3f} s" if calc is not None else ""
            else:
                roi.meta.pop("calc_time_s", None)
                mx, mn, calc_txt = "", "", ""
            row = [str(roi.roi_id), f"{roi.cx:.3f}", f"{roi.cy:.3f}",
                   f"{roi.w:.3f}", f"{roi.h:.3f}", f"{roi.angle_deg:.3f}",
                   cs, mx, mn, calc_txt, folder]
            r = self.table.rowCount()
            self.table.insertRow(r)
            for c, text in enumerate(row):
                self.table.setItem(r, c, QTableWidgetItem(text))

    def _on_table_select(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        rid = self.table.item(rows[0].row(), 0)
        if rid is None:
            return
        want = int(rid.text())
        self._select_roi_id(want)
        self._maybe_auto_analyze()

    # ----- through-focus contour -----
    def _is_auto_mode(self) -> bool:
        return self.radio_auto.isChecked()

    def _na_from_spin(self) -> float | None:
        """Read NA spin: special minimum → NULL / 讀 NA：最小值＝NULL。"""
        return normalize_na(float(self.sp_na.value()))

    def _set_na_spin(self, na: float | None) -> None:
        """Write NA into spin (None → NULL) / 寫入 NA（None→NULL）。"""
        v = normalize_na(na)
        self.sp_na.blockSignals(True)
        self.sp_na.setValue(NA_NULL_SENTINEL if v is None else float(v))
        self.sp_na.blockSignals(False)

    def _clamp_na_spin(self) -> None:
        """Snap (0, NA_MIN) up to NA_MIN after edit / 編輯後把過小值抬到 NA_MIN。"""
        raw = float(self.sp_na.value())
        if raw <= NA_NULL_SENTINEL:
            return
        if raw < NA_MIN:
            self.sp_na.blockSignals(True)
            self.sp_na.setValue(NA_MIN)
            self.sp_na.blockSignals(False)

    def _on_na_spin_changed(self, value: float) -> None:
        """Leaving NULL via step → land on NA_MIN / 離開 NULL 時落到 NA_MIN。"""
        if self._activating or self._updating:
            return
        if NA_NULL_SENTINEL < float(value) < NA_MIN:
            self.sp_na.blockSignals(True)
            self.sp_na.setValue(NA_MIN)
            self.sp_na.blockSignals(False)

    def _wavenumber_from_spin(self) -> float | None:
        """Read Wavenumber spin: special minimum → NULL。"""
        return normalize_wavenumber(float(self.sp_wavenumber.value()))

    def _set_wavenumber_spin(self, wavenumber: float | None) -> None:
        """Write Wavenumber into spin (None → NULL)。"""
        v = normalize_wavenumber(wavenumber)
        self.sp_wavenumber.blockSignals(True)
        self.sp_wavenumber.setValue(
            WN_NULL_SENTINEL if v is None else float(v))
        self.sp_wavenumber.blockSignals(False)

    def _clamp_wavenumber_spin(self) -> None:
        """Snap (0, WN_MIN) up to WN_MIN after edit。"""
        raw = float(self.sp_wavenumber.value())
        if raw <= WN_NULL_SENTINEL:
            return
        if raw < WN_MIN:
            self.sp_wavenumber.blockSignals(True)
            self.sp_wavenumber.setValue(WN_MIN)
            self.sp_wavenumber.blockSignals(False)

    def _on_wavenumber_spin_changed(self, value: float) -> None:
        """Leaving NULL via step → land on WN_MIN。"""
        if self._activating or self._updating:
            return
        if WN_NULL_SENTINEL < float(value) < WN_MIN:
            self.sp_wavenumber.blockSignals(True)
            self.sp_wavenumber.setValue(WN_MIN)
            self.sp_wavenumber.blockSignals(False)

    def _scale_settings(self) -> ScaleSettings:
        return ScaleSettings(
            x_pixel=float(self.sp_x_pixel.value()),
            y_pixel=float(self.sp_y_pixel.value()),
            z_step=float(self.sp_z_step.value()),
            wavenumber=self._wavenumber_from_spin(),
            unit=self.cmb_unit.currentText(),
            na=self._na_from_spin(),
        )

    def _on_scale_changed(self, *_args) -> None:
        """X/Y/Z/Normalize → rebuild TF so axes stay in sync.

        尺度變更時重建通焦圖，軸標與 µm／nm 同步（Auto／Manual 皆然）。
        """
        if self._activating or self._updating:
            return
        # Always refresh TF when a ROI+session exist so Unit syncs /
        # 有 ROI 與圖集時一律刷新，確保單位同步
        if self._session() is not None and self._selected_item() is not None:
            self.analyze_through_focus()
        else:
            self._maybe_auto_analyze()

    def _on_unit_changed(self, new_unit: str) -> None:
        """Convert X/Y/Z spin values when Unit switches; then rebuild TF.

        切換單位時換算 X／Y／Z 數值（維持物理尺寸），再重建通焦圖。
        """
        if self._activating or self._updating:
            return
        if new_unit not in (UNIT_UM, UNIT_NM):
            return
        old = self._scale_unit
        if old in (UNIT_UM, UNIT_NM) and old != new_unit:
            # display_new = display_old * (um→new) / (um→old)
            factor = um_to_unit_factor(new_unit) / um_to_unit_factor(old)
            for sp in (self.sp_x_pixel, self.sp_y_pixel, self.sp_z_step):
                sp.blockSignals(True)
                sp.setValue(float(sp.value()) * factor)
                sp.blockSignals(False)
            self.log.info(
                "Unit %s → %s (×%g on X/Y/Z) / 單位換算",
                old, new_unit, factor)
        self._scale_unit = new_unit
        self._on_scale_changed()

    def _on_lang_action(self, action: QAction) -> None:
        """EN / 中文 for TF display strings / 通焦顯示語言。"""
        if self._activating:
            return
        code = action.data() if action is not None else LANG_EN
        lang = normalize_lang(str(code or LANG_EN))
        self._apply_ui_lang(lang)

    def _apply_ui_lang(self, lang: str) -> None:
        lang = normalize_lang(lang)
        self._ui_lang = lang
        self.m_lang.setTitle(tr(lang, "lang_label"))
        self.lbl_unit.setText(tr(lang, "unit_label"))
        self.tf_preview.set_language(lang)
        act = self._lang_actions.get(lang)
        if act is not None and not act.isChecked():
            act.setChecked(True)

    def _maybe_auto_analyze(self) -> None:
        if self._activating:
            return
        if self._is_auto_mode():
            self.analyze_through_focus()

    def _on_snap_centroid_toggled(self, checked: bool) -> None:
        if not checked or self._activating or self._updating:
            return
        item = self._selected_item()
        if item is None:
            return
        if self._snap_item_to_focus_centroid(item, jump_step=True):
            self._refresh_table()
            self._maybe_auto_analyze()

    def _snap_item_to_focus_centroid(
        self, item: RoiItem, *, jump_step: bool = False
    ) -> bool:
        """Snap one ROI to in-focus centroid; return True if centre moved.

        將單一 ROI 對齊合焦質心；中心有移動回傳 True。
        """
        sess = self._session()
        if sess is None or not isValid(item):
            return False
        lums = [fr.luminance for fr in sess.frames]
        moved, fi, cen = snap_roi_to_focus_centroid(lums, sess.metas, item.roi)
        if cen is None:
            self.log.warning(
                "Snap centroid failed for ROI %d / ROI %d 質心對齊失敗",
                item.roi.roi_id, item.roi.roi_id)
            return False
        if moved:
            item.sync_from_roi()
            if item is self._selected_item():
                self._fill_spins(item.roi)
            self.log.info(
                "ROI %d snapped to focus centroid (%.2f, %.2f) @ step %d / "
                "ROI %d 對齊合焦質心 (%.2f, %.2f) @ 步 %d",
                item.roi.roi_id, cen[0], cen[1], fi + 1,
                item.roi.roi_id, cen[0], cen[1], fi + 1)
        if jump_step and sess.current_step != fi:
            self._set_session_step(fi)
        return moved

    def analyze_through_focus(self) -> None:
        """Build Focus×Radial contour for the selected ROI / 對選取 ROI 建通焦等高線。"""
        sess = self._session()
        item = self._selected_item()
        if sess is None:
            self.tf_preview.clear("No group / 尚未開啟圖集")
            return
        if item is None or not isValid(item):
            self.tf_preview.clear("No ROI selected / 尚未選取 ROI")
            return
        if self.chk_snap_centroid.isChecked():
            self._snap_item_to_focus_centroid(item, jump_step=False)
        # Completely outside image → nothing to compute /
        # 完全在影像外 → 無可計算內容
        if not self._roi_overlaps_image(item.roi):
            item.roi.meta.pop("calc_time_s", None)
            self.tf_preview.clear(
                "ROI outside image — skip / ROI 完全超出影像，不計算")
            self._refresh_table()
            self.log.info(
                "ROI %d fully outside image; skip analyze / "
                "ROI %d 完全超出影像，略過計算",
                item.roi.roi_id, item.roi.roi_id)
            return
        self._active_roi_id = item.roi.roi_id
        self._save_current_rois()
        t0 = _dt.datetime.now()
        try:
            self.progress.setRange(0, 0)
            self.progress.setFormat("Analyze…")
            QApplication.processEvents()
            scale = self._scale_settings()
            tf_map = build_through_focus_map(
                sess.frames, sess.metas, item.roi, scale,
                normalize=self.chk_normalize.isChecked())
            elapsed = (_dt.datetime.now() - t0).total_seconds()
            item.roi.meta["calc_time_s"] = float(elapsed)
            # Prefer False Color so the panel always shows an intensity image /
            # 預設 False Color，確保通焦區有強度影像
            if self.tf_preview.mode() not in PREVIEW_MODES:
                self.tf_preview.set_mode(MODE_FALSE_COLOR)
            self.tf_preview.set_save_meta(
                self._folder_name(), int(item.roi.roi_id))
            self.tf_preview.show_map(tf_map)
            self.tf_preview.set_focus_step(sess.current_step)
            # Nudge splitter if TF pane was squeezed / 若通焦區被壓扁則撐開
            sizes = self.groups_split.sizes()
            if len(sizes) >= 2 and sizes[1] < 200:
                total = max(sum(sizes), 500)
                self.groups_split.setSizes([max(total - 280, 120), 280])
            self._ensure_body_right_width(300)
            self._refresh_table()
            self.log.info(
                "Through-focus map ROI %d (%d steps, unit=%s, %.3f s) / "
                "通焦圖 ROI %d（%d 步，單位=%s，%.3f s）",
                item.roi.roi_id, tf_map.n_frames, tf_map.unit, elapsed,
                item.roi.roi_id, tf_map.n_frames, tf_map.unit, elapsed)
        except Exception as exc:  # noqa: BLE001
            self.tf_preview.clear(f"Analyze failed / 失敗:\n{exc}")
            self.log.error("Analyze failed / 失敗: %s", exc)
        finally:
            self._reset_progress()

    # ----- ROI settings CSV -----
    def save_roi_settings_dialog(self) -> None:
        """Save ROI settings as a new CSV / ROI 設定另存為新 CSV。"""
        self._prune_dead_items()
        if not self.items:
            QMessageBox.information(
                self, "Save ROI Settings", "No ROI / 尚無 ROI")
            return
        suggest = f"ROI_settings_{_dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save ROI Settings / ROI 設定另存", suggest,
            "CSV (*.csv)")
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        if os.path.exists(path):
            QMessageBox.warning(
                self, "Save ROI Settings",
                "File exists; will not overwrite / 檔案已存在，不覆寫")
            return
        self._save_current_rois()
        rois = [it.roi for it in self.items if isValid(it)]
        out = save_roi_settings(path, rois, folder_name=self._folder_name())
        self.log.info(
            "ROI settings saved / 已另存 ROI 設定: %s (%d)",
            safe_display_path(out), len(rois))

    def load_roi_settings_dialog(self) -> None:
        """Load ROI settings CSV onto the current group / 載入 ROI 設定到目前圖集。"""
        if self._session() is None:
            QMessageBox.information(
                self, "Load ROI Settings", "No group / 尚未開啟圖集")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Load ROI Settings / 載入 ROI 設定", "", "CSV (*.csv)")
        if not path:
            return
        try:
            rois = load_roi_settings(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Load ROI Settings", str(exc))
            self.log.error("Load ROI settings failed / 載入失敗: %s", exc)
            return
        if not rois:
            QMessageBox.information(
                self, "Load ROI Settings", "Empty file / 檔案無 ROI")
            return
        # Replace current ROI graphics / 取代目前 ROI
        self._prune_dead_items()
        scene = self.view.scene()
        self._activating = True
        try:
            scene.blockSignals(True)
            try:
                for it in list(self.items):
                    if isValid(it):
                        scene.removeItem(it)
                self.items.clear()
            finally:
                scene.blockSignals(False)
            self._active_roi_id = None
            prefer = None
            for roi in rois:
                self._add_item(roi, select=False)
                prefer = roi.roi_id
            self._select_roi_id(prefer)
            self._refresh_table()
        finally:
            self._activating = False
        self.log.info(
            "ROI settings loaded / 已載入 ROI 設定: %s (%d)", path, len(rois))
        self._maybe_auto_analyze()

    # ----- excel -----
    def _excel_export_options(self) -> Optional[ExcelExportOptions]:
        """Show options dialog; remember last choices / 顯示選項並記住上次勾選。"""
        s = QSettings("throughfocus-viewer", "ThroughFocusViewer")
        # One-shot: apply v0.2.21 Excel defaults over older remembered checks /
        # 一次性套用 v0.2.21 預設，覆蓋舊版記住的勾選
        if s.value("xlsx_defaults_rev", 0, type=int) < 1:
            s.setValue("xlsx_include_result", True)
            s.setValue("xlsx_include_roi", False)
            s.setValue("xlsx_include_tf", True)
            s.setValue("xlsx_include_defocus_2d", True)
            s.setValue("xlsx_separate_files", True)
            s.setValue("xlsx_defaults_rev", 1)
        initial = ExcelExportOptions(
            include_result=s.value("xlsx_include_result", True, type=bool),
            include_roi_profile=s.value("xlsx_include_roi", False, type=bool),
            include_tf=s.value("xlsx_include_tf", True, type=bool),
            include_defocus_2d=s.value(
                "xlsx_include_defocus_2d", True, type=bool),
            separate_files=s.value("xlsx_separate_files", True, type=bool),
        )
        dlg = ExcelExportDialog(self, initial=initial)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        opts = dlg.options()
        s.setValue("xlsx_include_result", opts.include_result)
        s.setValue("xlsx_include_roi", opts.include_roi_profile)
        s.setValue("xlsx_include_tf", opts.include_tf)
        s.setValue("xlsx_include_defocus_2d", opts.include_defocus_2d)
        s.setValue("xlsx_separate_files", opts.separate_files)
        return opts

    def export_excel(self) -> None:
        if self._excel_busy:
            self.log.warning(
                "Excel export already running / Excel 匯出進行中")
            return
        img = self._image()
        if img is None or not self.items:
            QMessageBox.information(self, "Export Excel",
                                    "No image or ROI / 沒有影像或 ROI")
            return
        opts = self._excel_export_options()
        if opts is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Excel", "", "Excel (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        targets = export_target_paths(path, opts)
        if not targets:
            QMessageBox.warning(self, "Export Excel",
                                "Select at least one item / 請至少勾選一項")
            return
        unique_paths = sorted(set(targets.values()))
        for p in unique_paths:
            if os.path.exists(p):
                QMessageBox.warning(
                    self, "Export Excel",
                    f"File exists; will not overwrite / 檔案已存在，不覆寫:\n{p}")
                return

        header = RESULT_COLUMNS
        rows = []
        for r in range(self.table.rowCount()):
            rows.append([self.table.item(r, c).text()
                         if self.table.item(r, c) else ""
                         for c in range(self.table.columnCount())])
        scale = self._scale_settings()
        do_norm = self.chk_normalize.isChecked()
        sess = self._session()
        need_roi = opts.include_roi_profile
        need_tf = opts.include_tf
        need_defocus = need_tf and opts.include_defocus_2d
        valid_items = [it for it in self.items if isValid(it)]
        n_roi = len(valid_items)
        n_frames = (len(sess.frames)
                    if (need_defocus and sess is not None) else 0)
        # Peak pre-pass (norm) + write pass per frame /
        # 歸一時多一趟峰值掃描；寫入仍逐幀
        peak_pass = 1 if (need_defocus and do_norm) else 0
        total_steps = max(
            n_roi * (1 + n_frames * (1 + peak_pass)) + len(unique_paths), 1)
        self.log.info(
            "Excel export start (ROI=%d, Result=%s, Profile=%s, TF=%s, "
            "Defocus2D=%s, separate=%s, stream=1) / "
            "開始匯出 Excel（ROI=%d，Result=%s，剖面=%s，通焦=%s，"
            "Defocus2D=%s，分檔=%s，分段寫入）",
            n_roi, opts.include_result, opts.include_roi_profile,
            opts.include_tf, opts.include_defocus_2d, opts.separate_files,
            n_roi, opts.include_result, opts.include_roi_profile,
            opts.include_tf, opts.include_defocus_2d, opts.separate_files)
        self._excel_busy = True
        self.act_export_excel.setEnabled(False)
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        # Freeze Log repaint during export; still append full lines /
        # 匯出中暫停 Log 重繪（文字仍完整寫入，結束一次顯示）
        self.log_panel.setUpdatesEnabled(False)
        self._set_progress(0, total_steps, "Excel 0%", force=True)
        t0 = _dt.datetime.now()
        step = 0
        writers: dict = {}
        written: List[str] = []
        n_plots = 0

        def _writer_for(key: str) -> Optional[ExcelWorkbookWriter]:
            p = targets.get(key)
            if not p:
                return None
            w = writers.get(p)
            if w is None:
                self.log.info(
                    "Excel open / 開啟寫入: %s", os.path.basename(p))
                w = ExcelWorkbookWriter(p)
                writers[p] = w
            return w

        try:
            # Result first (own file or shared) / 先寫 Result
            path_flags: dict = {}
            for key, p in targets.items():
                flags = path_flags.setdefault(
                    p, {"result": False, "roi": False, "tf": False})
                flags[key] = True
            for p, flags in path_flags.items():
                with_result = (
                    flags["result"] or flags["roi"] or flags["tf"])
                if with_result:
                    w = writers.get(p)
                    if w is None:
                        self.log.info(
                            "Excel open / 開啟寫入: %s", os.path.basename(p))
                        w = ExcelWorkbookWriter(p)
                        writers[p] = w
                    w.write_result(header, rows)
                    self.log.info(
                        "Excel Result sheet written / 已寫 Result: %s",
                        os.path.basename(p))

            for it in valid_items:
                roi = it.roi
                step += 1
                self._set_progress(
                    step, total_steps,
                    f"Excel ROI {roi.roi_id} ({step}/{total_steps})")
                # Fully outside → skip; partial OK (out-of-image = NaN) /
                # 完全超出才略過；部分超出仍算（影像外取樣為 NaN）
                if not roi.overlaps_image(img.width, img.height):
                    self.log.info(
                        "Excel skip ROI %d (fully outside image) / "
                        "略過 ROI %d（完全超出影像）",
                        roi.roi_id, roi.roi_id)
                    continue
                self.log.info(
                    "Excel ROI %d begin (TF=%s, Defocus2D=%s, frames=%d) / "
                    "開始 ROI %d（通焦=%s，Defocus2D=%s，幀=%d）",
                    roi.roi_id, need_tf, need_defocus, n_frames,
                    roi.roi_id, need_tf, need_defocus, n_frames)
                calc = roi.meta.get("calc_time_s")
                calc_txt = f"{float(calc):.3f} s" if calc is not None else ""
                info = [("ROI_ID", str(roi.roi_id)), ("CX", f"{roi.cx:g}"),
                        ("CY", f"{roi.cy:g}"), ("W", f"{roi.w:g}"),
                        ("H", f"{roi.h:g}"),
                        ("Rota_Angle", f"{roi.angle_deg:.3f}"),
                        ("ColorSpace",
                         color_space_label(img.bit_depth, img.channels)),
                        ("CalcTime", calc_txt),
                        ("FolderName", self._folder_name())]
                if need_roi:
                    w_roi = _writer_for("roi")
                    if w_roi is not None:
                        try:
                            prof: LineProfile = extract_profile(
                                img.luminance, roi)
                            sheet = ProfileSheet(
                                roi_id=roi.roi_id, info=info,
                                position=list(map(float, prof.position)),
                                intensity=list(map(float, prof.intensity)))
                        except Exception as exc:  # noqa: BLE001
                            sheet = ProfileSheet(
                                roi_id=roi.roi_id, info=info, error=str(exc))
                        w_roi.write_profile(sheet)
                        del sheet

                if need_tf and sess is not None and len(sess.frames) >= 1:
                    w_tf = _writer_for("tf")
                    if w_tf is None:
                        continue
                    tf_info = [
                        ("X_Pixel", f"{scale.x_pixel:g}"),
                        ("Y_Pixel", f"{scale.y_pixel:g}"),
                        ("Z_Step", f"{scale.z_step:g}"),
                        ("Wavenumber", format_wavenumber(scale.wavenumber)),
                        ("Unit", scale.unit),
                        ("NA", format_na(scale.na)),
                        ("FolderName", self._folder_name()),
                    ]
                    tf_err = ""
                    png = None
                    radial: list = []
                    focus: list = []
                    inten = np.zeros((0, 0))
                    unit = scale.unit
                    normalized = do_norm
                    try:
                        tf_map = build_through_focus_map(
                            sess.frames, sess.metas, roi, scale,
                            normalize=do_norm)
                        png = export_tf_png_bytes(
                            tf_map,
                            mode=self.tf_preview.mode(),
                            aspect=self.tf_preview.aspect_mode(),
                            width=640, height=480,
                            show_axes=self.tf_preview.show_axes(),
                            lang=self._ui_lang)
                        unit = tf_map.unit
                        radial = list(map(float, tf_map.radial))
                        focus = list(map(float, tf_map.focus))
                        inten = np.asarray(
                            tf_map.intensity, dtype=np.float64)
                        normalized = bool(tf_map.normalized)
                        del tf_map
                    except Exception as exc:  # noqa: BLE001
                        tf_err = str(exc)
                    tf_head = ThroughFocusSheet(
                        roi_id=roi.roi_id, unit=unit,
                        radial=radial, focus=focus, intensity=inten,
                        normalized=normalized, info=tf_info,
                        error=tf_err, image_png=png, frame_patches=[])
                    if png:
                        n_plots += 1
                    w_tf.start_tf_sheet(
                        tf_head, with_defocus_section=need_defocus)
                    # Free matrix / PNG refs after sheet head is written /
                    # 表頭寫入後釋放矩陣／PNG
                    del tf_head, inten, png, radial, focus

                    if need_defocus:
                        peak = 0.0
                        if do_norm:
                            for fi, fr in enumerate(sess.frames, 1):
                                step += 1
                                self._set_progress(
                                    step, total_steps,
                                    f"Excel peak ROI {roi.roi_id} "
                                    f"{fi}/{n_frames}")
                                try:
                                    _u, _v, patch = extract_roi_intensity_2d(
                                        fr.luminance, roi, step=1.0)
                                    arr = np.asarray(
                                        patch, dtype=np.float64)
                                    finite = arr[np.isfinite(arr)]
                                    if finite.size:
                                        peak = max(
                                            peak, float(finite.max()))
                                    del patch, arr, finite, _u, _v
                                except Exception:  # noqa: BLE001
                                    pass
                        for fi, fr in enumerate(sess.frames, 1):
                            step += 1
                            self._set_progress(
                                step, total_steps,
                                f"Excel Defocus ROI {roi.roi_id} "
                                f"frame {fi}/{n_frames}")
                            bname = os.path.basename(fr.path)
                            try:
                                u, v, patch = extract_roi_intensity_2d(
                                    fr.luminance, roi, step=1.0)
                                arr = np.asarray(patch, dtype=np.float64)
                                del patch
                                if do_norm and peak > 0:
                                    arr = arr / peak
                                block = DefocusFramePatch(
                                    basename=bname,
                                    u_pos=list(map(float, u)),
                                    v_pos=list(map(float, v)),
                                    intensity=arr)
                                del u, v, arr
                            except Exception as exc:  # noqa: BLE001
                                block = DefocusFramePatch(
                                    basename=bname, u_pos=[], v_pos=[],
                                    intensity=np.zeros((0, 0)),
                                    error=str(exc))
                            w_tf.write_tf_frame_patch(block)
                            del block
                    w_tf.end_tf_sheet()
                self.log.info(
                    "Excel ROI %d done / 完成 ROI %d",
                    roi.roi_id, roi.roi_id)

            # Info + save each open workbook / 各檔寫 Info 並存檔
            for p, flags in path_flags.items():
                step += 1
                self._set_progress(
                    step, total_steps,
                    f"Excel save {os.path.basename(p)}", force=True)
                w = writers.get(p)
                if w is None:
                    continue
                with_result = (
                    flags["result"] or flags["roi"] or flags["tf"])
                info_rows = [
                    ("Image", safe_display_path(img.path)),
                    ("Width", str(img.width)),
                    ("Height", str(img.height)),
                    ("X_Pixel", f"{scale.x_pixel:g}"),
                    ("Y_Pixel", f"{scale.y_pixel:g}"),
                    ("Z_Step", f"{scale.z_step:g}"),
                    ("Wavenumber", format_wavenumber(scale.wavenumber)),
                    ("Unit", scale.unit),
                    ("NA", format_na(scale.na)),
                    ("TF_Normalize", "Yes" if do_norm else "No"),
                    ("TF_Plots", str(n_plots if flags["tf"] else 0)),
                    ("Export_Result", "Yes" if with_result else "No"),
                    ("Export_ROI", "Yes" if flags["roi"] else "No"),
                    ("Export_TF", "Yes" if flags["tf"] else "No"),
                    ("Export_Defocus_2D",
                     "Yes" if (flags["tf"] and opts.include_defocus_2d)
                     else "No"),
                    ("Export_Stream", "Yes"),
                    ("Exported",
                     _dt.datetime.now().astimezone().isoformat(
                         timespec="seconds")),
                    ("App", f"{__app_name__} v{__version__}"),
                ]
                w.write_info(info_rows)
                w.save()
                written.append(p)
                writers[p] = None
                self.log.info(
                    "Excel saved / 已存檔: %s", os.path.basename(p))
        except Exception as exc:  # noqa: BLE001
            for w in writers.values():
                if w is not None:
                    w.abort()
            elapsed = (_dt.datetime.now() - t0).total_seconds()
            self.log.error(
                "Excel export failed after %.3f s / 匯出失敗（%.3f s）: %s",
                elapsed, elapsed, exc)
            QMessageBox.critical(self, "Export Excel", str(exc))
            self._excel_finish_cleanup()
            return

        elapsed = (_dt.datetime.now() - t0).total_seconds()
        self._set_progress(
            total_steps, total_steps, "Excel 100%", force=True)
        self.log.info(
            "Excel written in %.3f s (files=%d, ROI=%s, TF=%s, plots=%d, "
            "separate=%s, stream=1) / 已匯出 %.3f s（檔數=%d，ROI=%s，TF=%s，"
            "通焦圖=%d，分檔=%s，分段寫入）: %s",
            elapsed, len(written), opts.include_roi_profile, opts.include_tf,
            n_plots, opts.separate_files,
            elapsed, len(written), opts.include_roi_profile, opts.include_tf,
            n_plots, opts.separate_files, "; ".join(written))
        self._excel_finish_cleanup()

    def _excel_finish_cleanup(self) -> None:
        """Re-enable UI after Excel export / 匯出結束後恢復介面。"""
        self._excel_busy = False
        if hasattr(self, "act_export_excel"):
            self.act_export_excel.setEnabled(True)
        while QApplication.overrideCursor() is not None:
            QApplication.restoreOverrideCursor()
        # Show accumulated Log in one paint / 一次顯示累積的完整 Log
        if hasattr(self, "log_panel"):
            self.log_panel.setUpdatesEnabled(True)
            self.log_panel.ensureCursorVisible()
        self._reset_progress()

    # ----- help / log / drag -----
    def _append_log(self, text: str) -> None:
        self.log_panel.appendPlainText(text)

    def _on_cursor(self, x: float, y: float) -> None:
        self._status_xy.setText(f"X={x:.1f}  Y={y:.1f}")

    def _open_help(self, fragment: str = "") -> None:
        path = HELP_HTML
        if not path.is_file():
            self.log.warning("Help file not found / 找不到說明檔: %s", path)
            QMessageBox.warning(self, "Help", f"Not found / 找不到:\n{path}")
            return
        url = QUrl.fromLocalFile(str(path))
        if fragment:
            url.setFragment(fragment.lstrip("#"))
        QDesktopServices.openUrl(url)

    def open_help(self) -> None:
        self._open_help("")

    def open_release(self) -> None:
        self._open_help("version")

    def open_usage(self) -> None:
        self._open_help("usage")

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        self.load_paths(paths)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._save_settings()
        self.log.removeHandler(self._handler)
        super().closeEvent(event)

    def _restore_settings(self) -> None:
        s = QSettings("throughfocus-viewer", "ThroughFocusViewer")
        self.chk_fixed.setChecked(s.value("fixed_size", False, type=bool))
        auto = s.value("analyze_auto", True, type=bool)
        self.radio_auto.setChecked(bool(auto))
        self.radio_manual.setChecked(not bool(auto))
        self.chk_false_color.blockSignals(True)
        self.chk_edge.blockSignals(True)
        fc = bool(s.value("false_color", False, type=bool))
        edge = bool(s.value("preview_edge", False, type=bool))
        if fc and edge:
            edge = False  # exclusive / 互斥
        self.chk_false_color.setChecked(fc)
        self.chk_edge.setChecked(edge)
        self.chk_false_color.blockSignals(False)
        self.chk_edge.blockSignals(False)
        self.chk_snap_centroid.blockSignals(True)
        self.chk_snap_centroid.setChecked(
            s.value("snap_focus_centroid", False, type=bool))
        self.chk_snap_centroid.blockSignals(False)
        self.chk_normalize.blockSignals(True)
        self.chk_normalize.setChecked(
            s.value("tf_normalize", True, type=bool))
        self.chk_normalize.blockSignals(False)
        rota = str(s.value("roi_rota", ROI_ROTA_NONE, type=str) or ROI_ROTA_NONE)
        if rota not in ROI_ROTA_MODES:
            rota = ROI_ROTA_NONE
        self.cmb_roi_rota.blockSignals(True)
        self.cmb_roi_rota.setCurrentText(rota)
        self.cmb_roi_rota.blockSignals(False)
        preview_mode = str(s.value("preview_mode", MODE_FALSE_COLOR, type=str)
                            or MODE_FALSE_COLOR)
        # Edge was removed from TF; Contour/False Color only. Prefer False Color.
        # 通焦已無 Edge；僅 Contour／False Color，預設 False Color。
        if preview_mode not in PREVIEW_MODES:
            preview_mode = MODE_FALSE_COLOR
        self.tf_preview.set_mode(preview_mode)
        aspect = str(s.value("tf_aspect_mode", ASPECT_PHYSICAL, type=str)
                     or ASPECT_PHYSICAL)
        if aspect == "硬視窗":
            aspect = ASPECT_FILL  # migrate old label / 舊名遷移
        if aspect not in ASPECT_MODES:
            aspect = ASPECT_PHYSICAL
        self.tf_preview.set_aspect_mode(aspect)
        self.tf_preview.set_show_axes(
            s.value("tf_show_axes", True, type=bool))
        self.sp_x_pixel.blockSignals(True)
        self.sp_y_pixel.blockSignals(True)
        self.sp_z_step.blockSignals(True)
        self.cmb_unit.blockSignals(True)
        self.sp_x_pixel.setValue(s.value("x_pixel", 1.0, type=float))
        self.sp_y_pixel.setValue(s.value("y_pixel", 1.0, type=float))
        self.sp_z_step.setValue(s.value("z_step", 1.0, type=float))
        wn_raw = s.value("wavenumber", "")
        if wn_raw is None or wn_raw == "" or str(wn_raw).upper() == "NULL":
            self._set_wavenumber_spin(None)
        else:
            try:
                self._set_wavenumber_spin(float(wn_raw))
            except (TypeError, ValueError):
                self._set_wavenumber_spin(None)
        na_raw = s.value("na", "")
        if na_raw is None or na_raw == "" or str(na_raw).upper() == "NULL":
            self._set_na_spin(None)
        else:
            try:
                self._set_na_spin(float(na_raw))
            except (TypeError, ValueError):
                self._set_na_spin(None)
        unit = s.value("scale_unit", UNIT_UM, type=str)
        if unit not in (UNIT_UM, UNIT_NM):
            unit = UNIT_UM
        idx = self.cmb_unit.findText(unit)
        if idx >= 0:
            self.cmb_unit.setCurrentIndex(idx)
        self._scale_unit = unit
        lang = normalize_lang(str(s.value("ui_lang", LANG_EN, type=str)
                                  or LANG_EN))
        self._activating = True
        try:
            self._apply_ui_lang(lang)
        finally:
            self._activating = False
        self.sp_x_pixel.blockSignals(False)
        self.sp_y_pixel.blockSignals(False)
        self.sp_z_step.blockSignals(False)
        self.cmb_unit.blockSignals(False)
        geo = s.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        for key, split in (
            ("body_split", self.body_split),
            ("left_split", self.left_split),
            ("log_split", self.log_split),
            ("groups_split", self.groups_split),
        ):
            data = s.value(key)
            if data is not None:
                split.restoreState(data)
        # Clamp TF pane after restore so it never stays blank-height /
        # 還原後撐開通焦區，避免高度過低看起來沒影像
        self.groups_split.setChildrenCollapsible(False)
        self.tf_preview.setMinimumHeight(220)
        sizes = self.groups_split.sizes()
        if len(sizes) >= 2 and sizes[1] < 200:
            total = max(sum(sizes), 500)
            self.groups_split.setSizes([max(total - 280, 120), 280])
        # Clamp body right width so Mode/Aspect stay usable /
        # 右側過窄則撐開，避免通焦控制列擠疊、無法橫移
        self._ensure_body_right_width(300)

        # One-shot widen if older saves crushed the right pane /
        # 舊版設定若壓扁右側，一次性放寬
        s2 = QSettings("throughfocus-viewer", "ThroughFocusViewer")
        if s2.value("body_split_rev", 0, type=int) < 1:
            total = max(sum(self.body_split.sizes()), 1200)
            self.body_split.setSizes(
                [max(total - 420, 600), min(420, max(total // 3, 300))])
            s2.setValue("body_split_rev", 1)

    def _ensure_body_right_width(self, min_right: int = 300) -> None:
        """Widen right (Groups|TF) pane if restored too narrow.

        若右側（圖集｜通焦）過窄則撐開，方便橫向拖分割條。
        """
        sizes = self.body_split.sizes()
        if len(sizes) < 2 or sizes[1] >= min_right:
            return
        total = max(sum(sizes), min_right + 400)
        right = min(max(min_right, total // 3), total - 400)
        self.body_split.setSizes([total - right, right])

    def _save_settings(self) -> None:
        s = QSettings("throughfocus-viewer", "ThroughFocusViewer")
        s.setValue("fixed_size", self.chk_fixed.isChecked())
        s.setValue("analyze_auto", self.radio_auto.isChecked())
        s.setValue("false_color", self.chk_false_color.isChecked())
        s.setValue("preview_edge", self.chk_edge.isChecked())
        s.setValue("snap_focus_centroid", self.chk_snap_centroid.isChecked())
        s.setValue("tf_normalize", self.chk_normalize.isChecked())
        s.setValue("roi_rota", self.cmb_roi_rota.currentText())
        s.setValue("preview_mode", self.tf_preview.mode())
        s.setValue("tf_aspect_mode", self.tf_preview.aspect_mode())
        s.setValue("tf_show_axes", self.tf_preview.show_axes())
        s.setValue("x_pixel", self.sp_x_pixel.value())
        s.setValue("y_pixel", self.sp_y_pixel.value())
        s.setValue("z_step", self.sp_z_step.value())
        wn_val = self._wavenumber_from_spin()
        s.setValue(
            "wavenumber", "" if wn_val is None else float(wn_val))
        na_val = self._na_from_spin()
        s.setValue("na", "" if na_val is None else float(na_val))
        s.setValue("scale_unit", self.cmb_unit.currentText())
        s.setValue("ui_lang", self._ui_lang)
        s.setValue("geometry", self.saveGeometry())
        s.setValue("body_split", self.body_split.saveState())
        s.setValue("left_split", self.left_split.saveState())
        s.setValue("log_split", self.log_split.saveState())
        s.setValue("groups_split", self.groups_split.saveState())


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point / 進入點。

    No args: open DEFAULT_OPEN_FOLDER (Sample/) if it exists.
    無參數：若存在則開啟 DEFAULT_OPEN_FOLDER（Sample/）。
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    app_logger.install_global_hook()
    app = QApplication.instance() or QApplication(sys.argv)
    icon = _load_app_icon()
    if icon is not None and not icon.isNull():
        app.setWindowIcon(icon)
    win = MainWindow()
    win.show()
    if argv:
        win.load_paths(argv)
    elif path_isdir(str(DEFAULT_OPEN_FOLDER)):
        win.load_paths([str(DEFAULT_OPEN_FOLDER)])
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
