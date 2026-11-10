"""Result table helpers and the Excel (.xlsx) export of the ROI editor.

ROI 編輯器的 Result 表格輔助函式與 Excel（.xlsx）匯出。

Result columns (2026-10-29 request) / Result 欄位（2026-10-29 需求）:
    CX, CY, W, H, Rota_Angle, ColorSpace (bit depth), Max, Min, MTF50, MTF30.
    Max / Min = highest / lowest luminance of the pixels whose centres lie
    inside the ROI. MTF50 / MTF30 come from the last MTF run (cycles/px) and
    are blank when MTF was not computed or the ROI changed since.
    Max／Min＝像素中心落在 ROI 內的最大／最小亮度；MTF50／MTF30 取自最後一次
    MTF（cycles/px），未計算或 ROI 已變更時為空白。

Excel workbook / Excel 活頁簿:
    * sheet "Result": the Result table exactly as shown / 與畫面相同的 Result 表格
    * one sheet "ROI_<id>" per ROI: Line Profile data (dark -> bright, same as
      the Line Profile analysis) and a line chart / 每個 ROI 一頁：Line Profile
      數據（暗到亮，與 Line Profile 分析相同）與折線圖
    * sheet "TF_ROI_<id>": Focus×Radial matrix + embedded TF plot PNG,
      then each defocus frame's ROI 2-D intensity (Position_px), separated
      by basename top→bottom /
      Focus×Radial 矩陣＋嵌入通焦圖 PNG，其下依序為各 Defocus 幀的 ROI
      2-D 強度（Position_px），以 basename 分隔（上→下）
    * sheet "Info": image and export details / 影像與匯出資訊
    The file is always NEW: an existing path is refused, never overwritten.
    一律建立新檔：路徑已存在時拒絕，絕不覆寫。
    openpyxl is imported only here, so the editor runs without it.
    只在此處匯入 openpyxl，未安裝時編輯器仍可使用。
"""

from __future__ import annotations

import io
import math
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from viewer.roi import RotatedRoi

# Optional progress hook: (done_steps, total_steps, message) /
# 可選進度回呼：（已完成、總步數、訊息）
ProgressCb = Optional[Callable[[int, int, str], None]]


def _intensity_rows(inten: np.ndarray, v: Sequence[float],
                    n_u: int) -> List[list]:
    """Build append-ready rows; non-finite → None / 組成可 append 列；非有限→None。"""
    arr = np.asarray(inten, dtype=np.float64)
    rows: List[list] = []
    for i, vval in enumerate(v):
        row: list = [float(vval)]
        if i < arr.shape[0]:
            src = arr[i]
            for j in range(n_u):
                raw = src[j] if j < src.shape[0] else None
                row.append(
                    float(raw) if raw is not None and np.isfinite(raw)
                    else None)
        else:
            row.extend([None] * n_u)
        rows.append(row)
    return rows

_CHANNEL_NAMES = {1: "Gray", 2: "Gray+A", 3: "RGB", 4: "RGBA"}


@dataclass
class ExcelExportOptions:
    """Which Excel parts to write / 可自訂匯出的 Excel 項目。"""

    include_result: bool = True
    include_roi_profile: bool = False  # ROI_* Line Profile sheets
    include_tf: bool = True  # TF_ROI_* matrix + plot
    # Per-defocus ROI 2-D blocks under TF (needs include_tf) /
    # 通焦下方各 Defocus 2-D（需勾選通焦）
    include_defocus_2d: bool = True
    # Split files; *_ROI / *_TF still embed Result sheet /
    # 分檔時 *_ROI／*_TF 仍含 Result 表
    separate_files: bool = True


def export_target_paths(base_path: str, opts: ExcelExportOptions
                        ) -> Dict[str, str]:
    """Map content key → path (single or split) / 內容鍵→路徑（單一或分檔）。

    Keys: ``result``, ``roi``, ``tf``. Empty dict if nothing selected.
    """
    root, ext = os.path.splitext(base_path)
    if not ext.lower() == ".xlsx":
        ext = ".xlsx"
        root = base_path
    selected = []
    if opts.include_result:
        selected.append("result")
    if opts.include_roi_profile:
        selected.append("roi")
    if opts.include_tf:
        selected.append("tf")
    if not selected:
        return {}
    if not opts.separate_files or len(selected) == 1:
        return {k: f"{root}{ext}" for k in selected}
    suffix = {"result": "_Result", "roi": "_ROI", "tf": "_TF"}
    return {k: f"{root}{suffix[k]}{ext}" for k in selected}


def color_space_label(bit_depth: int, channels: int) -> str:
    """ColorSpace cell, e.g. "Gray 8-bit", "RGB 16-bit", "Gray 32-bit float".

    ColorSpace 欄位文字，例如 "Gray 8-bit"。

    Args:
        bit_depth: 8, 16 or 32 (float) / 位元深度。
        channels: Channels in the file / 檔案通道數。

    Returns:
        str: Label / 文字。
    """
    name = _CHANNEL_NAMES.get(int(channels), f"{int(channels)}ch")
    suffix = " float" if int(bit_depth) == 32 else ""
    return f"{name} {int(bit_depth)}-bit{suffix}"


def roi_pixel_range(luminance: np.ndarray, roi: RotatedRoi
                    ) -> Optional[Tuple[float, float]]:
    """(Max, Min) luminance of the pixels whose centres are inside ``roi``.

    像素中心在 ROI 內的 (最大, 最小) 亮度；ROI 完全在影像外時為 None。

    Args:
        luminance: H×W luminance / 亮度平面。
        roi: ROI (pixel-centre coordinates) / ROI（像素中心座標）。

    Returns:
        Optional[Tuple[float, float]]: (max, min), None if no pixel is inside.
            (最大, 最小)；沒有像素在內時為 None。
    """
    h, w = luminance.shape[:2]
    bx, by, bw, bh = roi.bbox()
    x0, y0 = max(0, math.floor(bx)), max(0, math.floor(by))
    x1, y1 = min(w - 1, math.ceil(bx + bw)), min(h - 1, math.ceil(by + bh))
    if x0 > x1 or y0 > y1:
        return None
    ys, xs = np.mgrid[y0:y1 + 1, x0:x1 + 1]
    vals = luminance[y0:y1 + 1, x0:x1 + 1][roi.contains(xs, ys)]
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return None
    return float(vals.max()), float(vals.min())


def format_level(value: float) -> str:
    """Code value text: integer if whole, else 1 decimal / 數值文字。"""
    return f"{value:.0f}" if float(value).is_integer() else f"{value:.1f}"


@dataclass
class ProfileSheet:
    """One ROI sheet of the workbook / 活頁簿中一個 ROI 的工作表。

    Attributes:
        roi_id: ROI_ID / ROI 編號。
        info: (label, value) pairs shown beside the data / 資料旁的資訊。
        position: Profile positions (px along u) / 剖面位置。
        intensity: Mean intensity / 平均強度。
        error: Why no profile could be made ("" = ok) / 無法產生剖面的原因。
    """

    roi_id: int
    info: List[Tuple[str, str]] = field(default_factory=list)
    position: Sequence[float] = ()
    intensity: Sequence[float] = ()
    error: str = ""


@dataclass
class DefocusFramePatch:
    """One defocus frame's ROI 2-D intensity block / 單一 Defocus 幀 ROI 2-D 強度。"""

    basename: str
    u_pos: Sequence[float]  # Position_px along u (columns)
    v_pos: Sequence[float]  # Position_px along v (rows)
    intensity: np.ndarray  # (n_v, n_u)
    error: str = ""


@dataclass
class ThroughFocusSheet:
    """Through-focus map sheet (physical axes) / 通焦圖工作表（實際尺寸軸）。"""

    roi_id: int
    unit: str
    radial: Sequence[float]
    focus: Sequence[float]
    intensity: np.ndarray  # (n_focus, n_radial)
    normalized: bool
    info: List[Tuple[str, str]] = field(default_factory=list)
    error: str = ""
    image_png: Optional[bytes] = None  # embedded TF plot / 嵌入通焦圖
    # Per-frame 2-D patches below TF (top→bottom by stack order) /
    # 通焦下方各幀 2-D（依疊圖順序上→下）
    frame_patches: List[DefocusFramePatch] = field(default_factory=list)


def _cell(text: str):
    """Numeric text -> float, "" -> None, else the text / 數字轉為數值。"""
    if text is None or text == "":
        return None
    try:
        value = float(text)
    except (TypeError, ValueError):
        return text
    return value if math.isfinite(value) else text


# Rows reserved under embedded TF PNG so frame patches do not overlap /
# 通焦 PNG 下方預留列，避免與各幀區塊重疊
_TF_IMAGE_GAP_ROWS = 28


def _embed_tf_image_at(ps, sh: "ThroughFocusSheet", anchor_row: int) -> None:
    """Embed TF PNG at ``anchor_row`` (title already written) / 於該列嵌入通焦 PNG。"""
    if not sh.image_png:
        return
    from openpyxl.drawing.image import Image as XLImage

    bio = io.BytesIO(sh.image_png)
    xl_img = XLImage(bio)
    # Keep readable size in Excel / Excel 內保持可讀尺寸
    max_w, max_h = 520, 400
    if xl_img.width and xl_img.height:
        scale = min(max_w / float(xl_img.width), max_h / float(xl_img.height), 1.0)
        xl_img.width = int(xl_img.width * scale)
        xl_img.height = int(xl_img.height * scale)
    else:
        xl_img.width, xl_img.height = max_w, max_h
    # Image sits on the row below the title / 圖放在標題下一列
    ps.add_image(xl_img, f"A{anchor_row + 1}")


def _append_one_frame_patch(ps, patch: DefocusFramePatch, bold) -> None:
    """Append one Defocus 2-D block (basename + grid) / 寫入單一 Defocus 2-D 塊。"""
    ps.append([str(patch.basename)])
    ps.cell(row=ps.max_row, column=1).font = bold
    if patch.error:
        ps.append(["Error", patch.error])
        return
    u = list(patch.u_pos)
    v = list(patch.v_pos)
    header = ["Position_px"] + [float(x) for x in u]
    ps.append(header)
    ps.cell(row=ps.max_row, column=1).font = bold
    for row in _intensity_rows(
            np.asarray(patch.intensity, dtype=np.float64), v, len(u)):
        ps.append(row)


class ExcelWorkbookWriter:
    """Incremental xlsx writer: finish a section then free caller data.

    分段寫入 Excel：每完成一段即可釋放呼叫端資料，降低尖峰記憶體。
    Append-only (do not mix absolute ``cell`` seeks) /
    全程 append（勿混用絕對列 ``cell``）。
    """

    def __init__(self, path: str) -> None:
        if os.path.exists(path):
            raise FileExistsError(path)
        from openpyxl import Workbook
        from openpyxl.styles import Font

        self.path = path
        self._Font = Font
        self._bold = Font(bold=True)
        self._wb = Workbook()
        self._ws0 = self._wb.active
        self._ws0.title = "__pending__"
        self._tf_ps = None
        self._tf_patch_i = 0
        self._closed = False
        # Reserve path (create-only) so we never overwrite /
        # 先以 xb 佔住路徑，絕不覆寫
        with open(path, "xb"):
            pass

    def write_result(self, header: Sequence[str],
                     rows: Sequence[Sequence[str]]) -> None:
        """Write Result sheet immediately / 立刻寫入 Result 表。"""
        self._ensure_open()
        ws0 = self._ws0
        ws0.title = "Result"
        ws0.append(list(header))
        for row in rows:
            ws0.append([_cell(c) for c in row])
        for c in ws0[1]:
            c.font = self._bold
        ws0.freeze_panes = "A2"

    def write_profile(self, sh: ProfileSheet) -> None:
        """Write one ROI_* Line Profile sheet / 寫入一個 ROI_* 剖面表。"""
        from openpyxl.chart import Reference, ScatterChart, Series

        self._ensure_open()
        bold = self._bold
        ps = self._wb.create_sheet(f"ROI_{sh.roi_id}")
        ps.append(["Position_px", "Intensity"])
        for c in ps[1]:
            c.font = bold
        for z, v in zip(sh.position, sh.intensity):
            ps.append([float(z), float(v) if np.isfinite(v) else None])
        for k, (label, value) in enumerate(sh.info, 1):
            ps.cell(row=k, column=4, value=label).font = bold
            ps.cell(row=k, column=5, value=_cell(value))
        if sh.error:
            ps.cell(row=len(sh.info) + 1, column=4, value="Error").font = bold
            ps.cell(row=len(sh.info) + 1, column=5, value=sh.error)
        n = len(sh.position)
        if n >= 2:
            chart = ScatterChart()
            chart.title = f"Line Profile ROI {sh.roi_id}"
            chart.style = 13
            chart.x_axis.title = "Position (px, along u)"
            chart.y_axis.title = "Intensity"
            chart.legend = None
            xs = Reference(ps, min_col=1, min_row=2, max_row=n + 1)
            ys = Reference(ps, min_col=2, min_row=1, max_row=n + 1)
            series = Series(ys, xs, title_from_data=True)
            series.marker.symbol = "none"
            series.smooth = False
            chart.series.append(series)
            chart.width, chart.height = 18, 10
            ps.add_chart(chart, "G2")

    def start_tf_sheet(self, sh: ThroughFocusSheet, *,
                       with_defocus_section: bool = False) -> None:
        """Write TF matrix + plot; patches via ``write_tf_frame_patch``.

        先寫通焦矩陣＋圖；各 Defocus 2-D 之後用 ``write_tf_frame_patch``。
        ``sh.frame_patches`` is ignored here / 此處忽略 ``frame_patches``。
        """
        self._ensure_open()
        if self._tf_ps is not None:
            raise RuntimeError("TF sheet already open / 已有開啟中的 TF 表")
        bold = self._bold
        ps = self._wb.create_sheet(f"TF_ROI_{sh.roi_id}")
        unit = sh.unit or ""
        if sh.error:
            ps.append(["Error", sh.error])
            for label, value in sh.info:
                ps.append([None, None, None, label, _cell(value)])
                ps.cell(row=ps.max_row, column=4).font = bold
            ps.append([])
            if sh.image_png:
                ps.append(["Through-Focus Plot / 通焦圖"])
                _embed_tf_image_at(ps, sh, ps.max_row)
                for _ in range(_TF_IMAGE_GAP_ROWS):
                    ps.append([])
            else:
                ps.append([])
        else:
            radial = list(sh.radial)
            focus = list(sh.focus)
            inten = np.asarray(sh.intensity, dtype=np.float64)
            header = [f"Focus\\Radial [{unit}]"] + [float(r) for r in radial]
            ps.append(header)
            for c in ps[1]:
                c.font = bold
            for row in _intensity_rows(inten, focus, len(radial)):
                ps.append(row)
            ps.freeze_panes = "B2"
            ps.append([])
            ps.append([
                "Normalized",
                "Yes (peak=1)" if sh.normalized else "No (raw)"])
            ps.cell(row=ps.max_row, column=1).font = bold
            for label, value in sh.info:
                ps.append([label, _cell(value)])
                ps.cell(row=ps.max_row, column=1).font = bold
            ps.append([])
            if sh.image_png:
                ps.append(["Through-Focus Plot / 通焦圖"])
                _embed_tf_image_at(ps, sh, ps.max_row)
                for _ in range(_TF_IMAGE_GAP_ROWS):
                    ps.append([])
            else:
                ps.append([])
        if with_defocus_section:
            ps.append(["Defocus ROI intensity (2D, Position_px) / "
                       "各 Defocus ROI 強度（2D，Position_px）"])
            ps.cell(row=ps.max_row, column=1).font = bold
            ps.append([])
        self._tf_ps = ps
        self._tf_patch_i = 0

    def write_tf_frame_patch(self, patch: DefocusFramePatch) -> None:
        """Append one Defocus 2-D block then caller may free it /
        寫入一塊 Defocus 2-D 後，呼叫端即可釋放該塊。"""
        self._ensure_open()
        if self._tf_ps is None:
            raise RuntimeError("No TF sheet started / 尚未 start_tf_sheet")
        ps = self._tf_ps
        if self._tf_patch_i > 0:
            ps.append(["-", "-", "-"])
        _append_one_frame_patch(ps, patch, self._bold)
        self._tf_patch_i += 1

    def end_tf_sheet(self) -> None:
        """Close current TF sheet streaming / 結束目前 TF 表串流。"""
        self._tf_ps = None
        self._tf_patch_i = 0

    def write_info(self, info: Sequence[Tuple[str, str]]) -> None:
        """Write Info sheet / 寫入 Info 表。"""
        self._ensure_open()
        inf = self._wb.create_sheet("Info")
        for label, value in info:
            inf.append([label, value])
        for row in inf.iter_rows(min_col=1, max_col=1):
            row[0].font = self._bold

    def save(self) -> str:
        """Flush workbook to reserved path (no BytesIO copy) /
        直接存到已佔位路徑（不經 BytesIO 加倍記憶體）。"""
        self._ensure_open()
        if self._tf_ps is not None:
            self.end_tf_sheet()
        if self._ws0.title == "__pending__":
            self._wb.remove(self._ws0)
        # Path was created empty with xb; openpyxl overwrites that stub /
        # 路徑已用 xb 建立空檔；openpyxl 覆寫該占位檔
        self._wb.save(self.path)
        self._closed = True
        self._wb = None
        return self.path

    def abort(self) -> None:
        """Discard workbook and remove reserved path / 放棄並刪除占位檔。"""
        self._tf_ps = None
        self._wb = None
        self._closed = True
        try:
            if os.path.exists(self.path) and os.path.getsize(self.path) == 0:
                os.remove(self.path)
            elif os.path.exists(self.path):
                # Partial write — still remove incomplete export /
                # 不完整匯出也刪除，避免殘留半成品
                os.remove(self.path)
        except OSError:
            pass

    def _ensure_open(self) -> None:
        if self._closed or self._wb is None:
            raise RuntimeError("Writer already closed / Writer 已關閉")


def write_result_xlsx(path: str, header: Sequence[str],
                      rows: Sequence[Sequence[str]],
                      sheets: Sequence[ProfileSheet],
                      info: Sequence[Tuple[str, str]],
                      tf_sheets: Optional[Sequence[ThroughFocusSheet]] = None,
                      *,
                      include_result: bool = True,
                      include_roi_profile: bool = True,
                      include_tf: bool = True,
                      progress: ProgressCb = None,
                      ) -> str:
    """Writes selected Result / ROI_* / TF_ROI_* parts to a NEW file.

    依選項將 Result、ROI_* Line Profile、TF_ROI_* 通焦圖寫成新檔（絕不覆寫）。
    Convenience wrapper over ``ExcelWorkbookWriter`` (streams patches) /
    便捷包裝 ``ExcelWorkbookWriter``（逐塊寫入 patches）。
    """
    use_profiles = include_roi_profile and bool(sheets)
    use_tf = include_tf and bool(tf_sheets)
    if not (include_result or use_profiles or use_tf):
        raise ValueError("No Excel content selected / 未選取任何匯出項目")

    def _p(done: int, total: int, msg: str) -> None:
        if progress is not None:
            progress(done, total, msg)

    tf_list = list(tf_sheets or []) if use_tf else []
    patch_steps = sum(max(len(t.frame_patches), 1) for t in tf_list)
    total_prog = max(patch_steps + 2, 1)
    step_prog = 0
    _p(step_prog, total_prog, "Excel build workbook")

    writer = ExcelWorkbookWriter(path)
    try:
        if include_result:
            writer.write_result(header, rows)
        if use_profiles:
            for sh in sheets:
                writer.write_profile(sh)
        if use_tf:
            for tf in tf_list:
                patches = list(tf.frame_patches)
                writer.start_tf_sheet(
                    tf, with_defocus_section=bool(patches))
                # Drop retained list on sheet to free refs after stream /
                # 串流後釋放 sheet 上保留的列表參照
                tf.frame_patches = []
                for fi, patch in enumerate(patches):
                    _p(step_prog + fi, total_prog,
                       f"Excel Defocus 2D {fi + 1}/{len(patches)}")
                    writer.write_tf_frame_patch(patch)
                writer.end_tf_sheet()
                step_prog += max(len(patches), 1)
        writer.write_info(info)
        _p(max(total_prog - 1, 0), total_prog, "Excel saving…")
        writer.save()
        _p(total_prog, total_prog, "Excel saved")
    except Exception:
        writer.abort()
        raise
    return path
