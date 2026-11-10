"""Save / load ROI settings CSV (geometry only).

ROI 設定 CSV 另存／載入（僅幾何，不含演算法結果）。
"""

from __future__ import annotations

import csv
import datetime as _dt
import os
from typing import List, Optional, Sequence, Tuple

from viewer import __version__
from viewer.roi import RotatedRoi, normalize_angle_deg

ROI_SETTING_COLUMNS: List[str] = [
    "ROI_ID", "CX", "CY", "W", "H", "Rota_Angle",
    "FolderName", "CalcTime_s", "Timestamp", "Version",
]


def save_roi_settings(
    path: str,
    rois: Sequence[RotatedRoi],
    *,
    folder_name: str = "",
) -> str:
    """Write ROI settings as a new CSV (never overwrites).

    寫出 ROI 設定為新 CSV（絕不覆寫）。

    Raises:
        FileExistsError: Path already exists / 路徑已存在。
        OSError: Write failure / 寫檔失敗。
    """
    path = os.path.abspath(path)
    if os.path.exists(path):
        raise FileExistsError(path)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    stamp = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(ROI_SETTING_COLUMNS)
        for roi in rois:
            calc = roi.meta.get("calc_time_s")
            calc_txt = f"{float(calc):.6g}" if calc is not None else ""
            writer.writerow([
                str(int(roi.roi_id)),
                repr(float(roi.cx)),
                repr(float(roi.cy)),
                repr(float(roi.w)),
                repr(float(roi.h)),
                repr(float(roi.angle_deg)),
                folder_name,
                calc_txt,
                stamp,
                __version__,
            ])
    return path


def load_roi_settings(path: str) -> List[RotatedRoi]:
    """Load ROI settings CSV / 讀取 ROI 設定 CSV。"""
    rois: List[RotatedRoi] = []
    with open(path, "r", newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if not row:
                continue
            rid = int(float(row.get("ROI_ID") or row.get("roi_id") or 0))
            cx = float(row.get("CX") or row.get("cx") or 0)
            cy = float(row.get("CY") or row.get("cy") or 0)
            w = float(row.get("W") or row.get("dx") or 1)
            h = float(row.get("H") or row.get("dy") or 1)
            ang = float(row.get("Rota_Angle") or row.get("angle_deg") or 0)
            meta = {}
            calc = row.get("CalcTime_s") or ""
            if calc not in ("", None):
                try:
                    meta["calc_time_s"] = float(calc)
                except ValueError:
                    pass
            rois.append(RotatedRoi(
                cx=cx, cy=cy, dx=max(w, 1e-6), dy=max(h, 1e-6),
                angle_deg=normalize_angle_deg(ang), roi_id=rid,
                source="file", meta=meta))
    return rois
