"""Image loading and luminance conversion.

影像讀取與亮度（Y）轉換。

Luminance formula (ITU-R BT.709, same weights as Video TMT Charts.dll):
    Y = 0.2126 * R + 0.7152 * G + 0.0722 * B
applied directly to the stored code values (no gamma linearisation in v0.1).
亮度公式（ITU-R BT.709，與 Video TMT Charts.dll 相同權重）：
    Y = 0.2126 * R + 0.7152 * G + 0.0722 * B
直接套用在儲存的數值上（v0.1 不做 gamma 線性化）。
"""

from __future__ import annotations

from dataclasses import dataclass
import glob
import os
import re
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

# Supported extensions / 支援的副檔名
SUPPORTED_EXTENSIONS: Tuple[str, ...] = (
    ".png", ".bmp", ".tif", ".tiff", ".jpg", ".jpeg")

_GLOB_CHARS = ("*", "?", "[")


def display_path(path: str) -> str:
    """Absolute path without Windows ``\\\\?\\`` prefix (for UI / logs).

    去掉 Windows ``\\\\?\\`` 前綴的絕對路徑（供介面／日誌）。
    """
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[8:]
    if path.startswith("\\\\?\\"):
        return path[4:]
    return path


def io_path(path: str) -> str:
    """Path for Win32 file APIs; uses ``\\\\?\\`` when needed for long paths.

    供檔案 API 使用的路徑；超過 MAX_PATH 時加上 ``\\\\?\\``。
    """
    abs_path = os.path.abspath(display_path(path))
    if os.name != "nt":
        return abs_path
    if abs_path.startswith("\\\\?\\"):
        return abs_path
    if abs_path.startswith("\\\\"):
        # UNC: \\server\share -> \\?\UNC\server\share
        return "\\\\?\\UNC\\" + abs_path[2:]
    return "\\\\?\\" + abs_path


def path_exists(path: str) -> bool:
    """True if path exists (Windows long-path safe) / 路徑是否存在（支援長路徑）。"""
    return os.path.exists(io_path(path))


def path_isfile(path: str) -> bool:
    """True if path is a file (Windows long-path safe) / 是否為檔案（支援長路徑）。"""
    return os.path.isfile(io_path(path))


def path_isdir(path: str) -> bool:
    """True if path is a directory (Windows long-path safe) / 是否為資料夾（支援長路徑）。"""
    return os.path.isdir(io_path(path))


def is_supported_image(path: str) -> bool:
    """True if the file extension is a supported image type / 副檔名是否為支援的影像。"""
    return os.path.splitext(display_path(path))[1].lower() in SUPPORTED_EXTENSIONS


def _natural_key(path: str) -> list:
    """Sort key: name, case-insensitive, numbers by value (img2 < img10).

    排序鍵：依檔名、不分大小寫、數字依數值（img2 排在 img10 前）。
    """
    name = os.path.basename(display_path(path)).lower()
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


def expand_image_args(args: Sequence[str]) -> Tuple[List[str], List[Tuple[str, str]]]:
    """Turns command-line arguments into image files, in order.

    Each argument may be an image file, a folder (its supported images, sorted
    by name, not recursive) or a glob pattern such as ``D:/data/*.bmp``
    (Windows cmd does not expand ``*`` itself). Duplicates are dropped.
    將命令列參數轉成影像檔清單（依序）。每個參數可以是影像檔、資料夾（其中支援的
    影像，依檔名排序、不含子資料夾）或萬用字元樣式（例如 ``*.bmp``；Windows cmd
    不會自己展開 ``*``）。重複的檔案只留一個。

    Args:
        args: Command-line arguments / 命令列參數。

    Returns:
        tuple: (image paths, [(argument, reason skipped)]) /
            （影像路徑清單，[（參數，略過原因）]）。
    """
    paths: List[str] = []
    skipped: List[Tuple[str, str]] = []
    seen = set()

    def add(found: List[str], arg: str, empty_reason: str) -> None:
        images = sorted(
            (f for f in found if path_isfile(f) and is_supported_image(f)),
            key=_natural_key)
        if not images:
            skipped.append((arg, empty_reason))
        for f in images:
            abs_f = display_path(os.path.abspath(display_path(f)))
            key = os.path.normcase(abs_f)
            if key not in seen:
                seen.add(key)
                paths.append(abs_f)

    for arg in args:
        arg = arg.strip().strip('"')
        if not arg:
            continue
        if path_isdir(arg):
            folder = display_path(os.path.abspath(display_path(arg)))
            names = os.listdir(io_path(folder))
            add([os.path.join(folder, n) for n in names], arg,
                "folder has no supported image / 資料夾內沒有支援的影像")
        elif path_isfile(arg):
            if is_supported_image(arg):
                add([arg], arg, "")
            else:
                skipped.append((arg, "unsupported format %s / 不支援的格式"
                                % (os.path.splitext(arg)[1] or "(none)")))
        elif any(c in arg for c in _GLOB_CHARS):
            add(glob.glob(arg), arg, "no supported image matches / 沒有符合的影像")
        else:
            skipped.append((arg, "not found / 找不到"))
    return paths, skipped


def list_images_in_folder(folder: str) -> Tuple[List[str], Optional[str]]:
    """Lists supported images in one folder (non-recursive, natural sort).

    列出資料夾內支援的影像（不含子資料夾，自然排序）。
    Supports Windows paths longer than MAX_PATH (260) via ``\\\\?\\``.
    透過 ``\\\\?\\`` 支援超過 MAX_PATH（260）的 Windows 路徑。

    Returns:
        (paths, None) on success, or ([], reason) if empty/missing /
        成功為（路徑清單，None）；失敗為（[]，原因）。
    """
    folder = display_path(os.path.abspath(display_path(folder.strip().strip('"'))))
    if not path_isdir(folder):
        return [], "not a folder / 不是資料夾"
    names = os.listdir(io_path(folder))
    found = [os.path.join(folder, n) for n in names]
    images = sorted(
        (f for f in found if path_isfile(f) and is_supported_image(f)),
        key=_natural_key)
    if not images:
        return [], "folder has no supported image / 資料夾內沒有支援的影像"
    return [display_path(os.path.abspath(display_path(f))) for f in images], None


# BT.709 luma weights (R, G, B) / BT.709 亮度權重（R, G, B）
BT709_WEIGHTS: Tuple[float, float, float] = (0.2126, 0.7152, 0.0722)
# BT.601 luma weights (R, G, B) / BT.601 亮度權重（R, G, B）
BT601_WEIGHTS: Tuple[float, float, float] = (0.299, 0.587, 0.114)


@dataclass
class LoadedImage:
    """A loaded image and its luminance plane / 已讀取的影像與亮度平面。

    Attributes:
        path: Absolute file path / 檔案絕對路徑。
        raw: Original pixel array (H×W or H×W×3, RGB order) / 原始像素陣列（RGB）。
        luminance: float64 H×W luminance in original code values.
            以原始數值單位表示的 float64 亮度陣列。
        bit_depth: 8, 16 or 32 (float) / 位元深度。
        channels: Number of channels in the file / 檔案通道數。
    """

    path: str
    raw: np.ndarray
    luminance: np.ndarray
    bit_depth: int
    channels: int

    @property
    def width(self) -> int:
        """Image width in px / 影像寬度（像素）。"""
        return int(self.luminance.shape[1])

    @property
    def height(self) -> int:
        """Image height in px / 影像高度（像素）。"""
        return int(self.luminance.shape[0])

    @property
    def max_code(self) -> float:
        """Full-scale code value (255, 65535 or data max) / 滿刻度數值。"""
        if self.bit_depth == 8:
            return 255.0
        if self.bit_depth == 16:
            return 65535.0
        return float(np.nanmax(self.luminance)) or 1.0


def to_luminance(
    rgb: np.ndarray, weights: Tuple[float, float, float] = BT709_WEIGHTS
) -> np.ndarray:
    """Converts an RGB(A) or gray array to float64 luminance.

    將 RGB(A) 或灰階陣列轉為 float64 亮度。

    Args:
        rgb: H×W, H×W×3 or H×W×4 array in RGB order / RGB 順序的陣列。
        weights: (wR, wG, wB) luma weights / 亮度權重。

    Returns:
        np.ndarray: H×W float64 luminance / H×W float64 亮度。

    Raises:
        ValueError: Unsupported array shape / 不支援的陣列形狀。
    """
    arr = np.asarray(rgb)
    if arr.ndim == 2:
        return arr.astype(np.float64)
    if arr.ndim == 3 and arr.shape[2] in (3, 4):
        w = np.asarray(weights, dtype=np.float64)
        return arr[..., :3].astype(np.float64) @ w
    if arr.ndim == 3 and arr.shape[2] == 1:
        return arr[..., 0].astype(np.float64)
    raise ValueError(
        f"Unsupported image shape {arr.shape} / 不支援的影像形狀 {arr.shape}")


def load_image(path: str) -> LoadedImage:
    """Loads PNG/BMP/TIFF/JPEG (8/16-bit, gray or RGB) incl. non-ASCII paths.

    讀取 PNG/BMP/TIFF/JPEG（8/16-bit、灰階或彩色），支援中文路徑。

    Args:
        path: Image file path / 影像檔路徑。

    Returns:
        LoadedImage: Loaded image / 已讀取的影像。

    Raises:
        FileNotFoundError: File does not exist / 檔案不存在。
        ValueError: Unsupported or unreadable file / 不支援或無法讀取的檔案。
    """
    abs_path = display_path(os.path.abspath(display_path(path)))
    if not path_isfile(abs_path):
        raise FileNotFoundError(f"File not found / 找不到檔案: {abs_path}")
    ext = os.path.splitext(abs_path)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported format {ext} / 不支援的格式 {ext}")
    # np.fromfile + imdecode: non-ASCII and Windows long paths (\\?\).
    # 使用 np.fromfile + imdecode：支援中文路徑與 Windows 長路徑（\\?\）。
    buffer = np.fromfile(io_path(abs_path), dtype=np.uint8)
    arr = cv2.imdecode(buffer, cv2.IMREAD_UNCHANGED)
    if arr is None:
        raise ValueError(
            f"Cannot decode image / 無法解碼影像: {abs_path}")
    if arr.ndim == 3:
        if arr.shape[2] == 3:
            arr = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)
        elif arr.shape[2] == 4:
            arr = cv2.cvtColor(arr, cv2.COLOR_BGRA2RGBA)
    if arr.dtype == np.uint8:
        bit_depth = 8
    elif arr.dtype == np.uint16:
        bit_depth = 16
    else:
        bit_depth = 32
    channels = 1 if arr.ndim == 2 else int(arr.shape[2])
    return LoadedImage(
        path=abs_path,
        raw=arr,
        luminance=to_luminance(arr),
        bit_depth=bit_depth,
        channels=channels,
    )


def save_image(path: str, array: np.ndarray) -> None:
    """Saves an array (gray or RGB) to PNG/BMP/TIFF, non-ASCII safe.

    將陣列（灰階或 RGB）存成 PNG/BMP/TIFF，支援中文路徑。

    Args:
        path: Output path / 輸出路徑。
        array: uint8/uint16 array, RGB order if 3-channel / 影像陣列（RGB）。

    Raises:
        ValueError: Encoding failed / 編碼失敗。
    """
    arr = array
    if arr.ndim == 3 and arr.shape[2] == 3:
        arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    out = display_path(path)
    ext = os.path.splitext(out)[1] or ".png"
    ok, encoded = cv2.imencode(ext, arr)
    if not ok:
        raise ValueError(f"Cannot encode image / 無法編碼影像: {out}")
    encoded.tofile(io_path(out))
