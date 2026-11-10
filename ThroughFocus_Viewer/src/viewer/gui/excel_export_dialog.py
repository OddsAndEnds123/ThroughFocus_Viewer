"""Excel export options dialog / Excel 匯出項目對話框。"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QGroupBox, QRadioButton,
    QVBoxLayout,
)

from viewer.result_export import ExcelExportOptions


class ExcelExportDialog(QDialog):
    """Choose Result / ROI_* / TF_ROI_* and single vs separate files.

    自訂 Result／ROI_*／TF_ROI_* 匯出項目，以及單一檔或分檔。
    """

    def __init__(self, parent=None,
                 initial: Optional[ExcelExportOptions] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export Excel / 匯出 Excel")
        self.setModal(True)
        opts = initial or ExcelExportOptions()

        lay = QVBoxLayout(self)

        box_items = QGroupBox("Content / 內容")
        items_lay = QVBoxLayout(box_items)
        self.chk_result = QCheckBox("Result")
        self.chk_result.setChecked(opts.include_result)
        self.chk_roi = QCheckBox("ROI profile")
        self.chk_roi.setChecked(opts.include_roi_profile)
        self.chk_roi.setToolTip("ROI_* Line Profile / ROI 線剖面")
        self.chk_tf = QCheckBox("Through-Focus")
        self.chk_tf.setChecked(opts.include_tf)
        self.chk_tf.setToolTip("TF_ROI_* matrix + plot / 通焦矩陣＋圖")
        self.chk_defocus_2d = QCheckBox("  + Defocus 2D")
        self.chk_defocus_2d.setChecked(opts.include_defocus_2d)
        self.chk_defocus_2d.setToolTip(
            "Per-frame ROI 2D under TF; basename; A/B/C = - between frames\n"
            "通焦下方各幀 2D；檔名分隔；圖間 A／B／C 填 -")
        items_lay.addWidget(self.chk_result)
        items_lay.addWidget(self.chk_roi)
        items_lay.addWidget(self.chk_tf)
        items_lay.addWidget(self.chk_defocus_2d)
        lay.addWidget(box_items)

        self.chk_tf.toggled.connect(self._sync_defocus_enabled)
        self._sync_defocus_enabled(self.chk_tf.isChecked())

        box_out = QGroupBox("Output / 輸出")
        out_lay = QVBoxLayout(box_out)
        self.radio_single = QRadioButton("Single file / 單一檔")
        self.radio_separate = QRadioButton("Separate / 分檔")
        self.radio_separate.setToolTip(
            "*_Result / *_ROI / *_TF  (*_ROI／*_TF include Result)")
        if opts.separate_files:
            self.radio_separate.setChecked(True)
        else:
            self.radio_single.setChecked(True)
        out_lay.addWidget(self.radio_single)
        out_lay.addWidget(self.radio_separate)
        lay.addWidget(box_out)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _sync_defocus_enabled(self, tf_on: bool) -> None:
        self.chk_defocus_2d.setEnabled(bool(tf_on))
        if not tf_on:
            self.chk_defocus_2d.setChecked(False)

    def _accept_if_valid(self) -> None:
        if not (self.chk_result.isChecked()
                or self.chk_roi.isChecked()
                or self.chk_tf.isChecked()):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "Export Excel",
                "Select at least one item / 請至少勾選一項")
            return
        self.accept()

    def options(self) -> ExcelExportOptions:
        tf_on = self.chk_tf.isChecked()
        return ExcelExportOptions(
            include_result=self.chk_result.isChecked(),
            include_roi_profile=self.chk_roi.isChecked(),
            include_tf=tf_on,
            include_defocus_2d=tf_on and self.chk_defocus_2d.isChecked(),
            separate_files=self.radio_separate.isChecked(),
        )
