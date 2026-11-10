"""Universal exception logger and debugger module.

通用 Python 異常捕獲與日誌記錄模組。

Follows the project logger spec (python-exception-logger v2) and the Google
Python Style Guide. Log files are written to a ``Log/`` folder next to the
application and named ``YYYY-MM-DD_UTC+X_24h_HHmm_<BugType>.log``.
遵循專案日誌規範（python-exception-logger v2）與 Google Python 風格指南。
日誌檔寫入程式旁的 ``Log/`` 資料夾，檔名格式為
``YYYY-MM-DD_UTC+X_24h_HHmm_<BugType>.log``。
"""

from __future__ import annotations

from datetime import datetime
import logging
import os
import re
import sys
import traceback
from types import TracebackType
from typing import Callable, List, Optional, TextIO, Tuple, Type

# Name of the application-wide (non-exception) logger.
# 應用程式一般訊息用的 Logger 名稱。
APP_LOGGER_NAME: str = "viewer"

# True after a CJK-capable console font is applied (else strip CJK on console).
# 成功套用中文字型後為 True（否則主控台輸出去掉中文，避免 ``）。
_console_font_ok: bool = False

# Bilingual "English / 中文" or bare CJK → keep English for Raster Font consoles.
# 雙語「English / 中文」或純中文 → 點陣主控台只留英文。
_RE_BLINGUAL_CJK = re.compile(r"\s*/\s*[\u3400-\u9fff][^:\n]*")
_RE_CJK = re.compile(r"[\u3400-\u9fff]+")

# Win32 STD handles / Win32 標準控制代碼
_STD_OUTPUT_HANDLE = -11
_STD_ERROR_HANDLE = -12

# TrueType faces that can render CJK in conhost (Raster Fonts show U+FFFD).
# 可在 conhost 顯示中文的 TrueType 字型（點陣字會變成 ``）。
_CONSOLE_FONT_CANDIDATES: Tuple[str, ...] = (
    "NSimSun",
    "新細明體",
    "MingLiU",
    "Microsoft JhengHei",
    "Consolas",
    "Lucida Console",
)


def _set_console_cjk_font() -> bool:
    """Switch active console to a TrueType CJK-capable font.

    將作用中主控台改為可顯示中文的 TrueType 字型。
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class _COORD(ctypes.Structure):
            _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]

        class _CONSOLE_FONT_INFOEX(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.ULONG),
                ("nFont", wintypes.DWORD),
                ("dwFontSize", _COORD),
                ("FontFamily", wintypes.UINT),
                ("FontWeight", wintypes.UINT),
                ("FaceName", wintypes.WCHAR * 32),
            ]

        kernel32 = ctypes.windll.kernel32
        # Font is per-console; stdout handle is fine even when logging to stderr.
        # 字型屬整個主控台；用 stdout 控制代碼即可。
        handle = kernel32.GetStdHandle(_STD_OUTPUT_HANDLE)
        if handle in (0, -1, None):
            return False
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False

        FF_MODERN = 48
        TMPF_TRUETYPE = 4
        for face in _CONSOLE_FONT_CANDIDATES:
            info = _CONSOLE_FONT_INFOEX()
            info.cbSize = ctypes.sizeof(_CONSOLE_FONT_INFOEX)
            info.nFont = 0
            info.dwFontSize.X = 0
            info.dwFontSize.Y = 16
            info.FontFamily = FF_MODERN | TMPF_TRUETYPE
            info.FontWeight = 400
            info.FaceName = face
            if kernel32.SetCurrentConsoleFontEx(handle, False, ctypes.byref(info)):
                return True
        return False
    except Exception:
        return False


def _console_encoding() -> str:
    """Encoding matching the active console output CP / 對應主控台輸出代碼頁。"""
    if sys.platform != "win32":
        return "utf-8"
    try:
        import ctypes

        cp = int(ctypes.windll.kernel32.GetConsoleOutputCP())
        if cp in (0, 65001):
            return "utf-8"
        return f"cp{cp}"
    except Exception:
        return "utf-8"


def _console_text(text: str) -> str:
    """Keep CJK only when console font can render it / 僅在字型可顯示時保留中文。"""
    if _console_font_ok:
        return text
    text = _RE_BLINGUAL_CJK.sub("", text)
    text = _RE_CJK.sub("", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text


def configure_windows_console() -> None:
    """Prepare Windows console for Chinese log lines (font + matching stdio).

    準備 Windows 主控台以正確顯示中文日誌（字型＋對齊 stdio 編碼）。

    Note: Do **not** force CP 65001 here — with Raster Fonts that yields U+FFFD
    for CJK. Prefer system CP (cp950 on zh-TW) + TrueType font + WriteConsoleW.
    注意：此處**不要**強制 65001；點陣字下中文會變成 ``。改採系統代碼頁
    （繁中多為 cp950）＋ TrueType 字型＋ WriteConsoleW。
    """
    global _console_font_ok
    if sys.platform != "win32":
        return
    _console_font_ok = _set_console_cjk_font()
    enc = _console_encoding()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding=enc, errors="replace")
        except Exception:
            pass


def _write_console_unicode(text: str, *, stderr: bool = True) -> bool:
    """Write Unicode via WriteConsoleW (code-page safe). False if redirected.

    以 WriteConsoleW 寫入 Unicode（不受代碼頁亂碼影響）；重新導向時回傳 False。
    """
    if sys.platform != "win32" or not text:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(
            _STD_ERROR_HANDLE if stderr else _STD_OUTPUT_HANDLE)
        if handle in (0, -1, None):
            return False
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False  # pipe / file redirect / 管線或檔案重新導向
        # WriteConsoleW limit ~64K chars; chunk long messages.
        # WriteConsoleW 單次約 64K 字元；長訊息分段寫入。
        chunk = 16384
        total = 0
        length = len(text)
        written = wintypes.DWORD(0)
        while total < length:
            part = text[total:total + chunk]
            buf = ctypes.create_unicode_buffer(part)
            if not kernel32.WriteConsoleW(
                    handle, buf, len(part), ctypes.byref(written), None):
                return False
            total += len(part)
        return True
    except Exception:
        return False


class WinSafeStreamHandler(logging.StreamHandler):
    """StreamHandler that prefers WriteConsoleW on a real Windows console.

    真實 Windows 主控台優先用 WriteConsoleW，避免 UTF-8／CP950 中文亂碼。
    """

    def __init__(self, stream: Optional[TextIO] = None) -> None:
        super().__init__(stream)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = _console_text(self.format(record)) + self.terminator
            is_err = self.stream is sys.stderr
            if _write_console_unicode(msg, stderr=is_err):
                return
            stream = self.stream
            stream.write(msg)
            self.flush()
        except RecursionError:
            raise
        except Exception:
            self.handleError(record)

# Optional override of the log folder (used by tests).
# 可覆寫的日誌資料夾路徑（測試時使用）。
_log_dir_override: Optional[str] = None

# Extra listeners notified after an exception is logged (e.g. GUI panel).
# 例外記錄後要通知的監聽者（例如 GUI 的 Logger 面板）。
_exception_listeners: List[Callable[[str, str], None]] = []


def get_app_dir() -> str:
    """Returns the application folder (handles PyInstaller frozen builds).

    傳回應用程式所在資料夾（支援 PyInstaller 打包後的執行檔）。

    Returns:
        str: Absolute folder path / 資料夾絕對路徑。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    # viewer/app_logger.py -> app root is the parent of the package.
    # viewer/app_logger.py -> 程式根目錄為套件的上一層。
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def set_log_dir(path: Optional[str]) -> None:
    """Overrides the log folder (None restores the default ``<app>/Log``).

    覆寫日誌資料夾（傳入 None 則恢復預設 ``<app>/Log``）。

    Args:
        path: Folder path or None / 資料夾路徑或 None。
    """
    global _log_dir_override
    _log_dir_override = path


def get_log_dir() -> str:
    """Returns (and creates if needed) the log folder.

    傳回日誌資料夾（不存在時自動建立）。

    Returns:
        str: Log folder path / 日誌資料夾路徑。
    """
    log_dir = _log_dir_override or os.path.join(get_app_dir(), "Log")
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def build_log_filename(bug_type: str, now: Optional[datetime] = None) -> str:
    """Builds ``YYYY-MM-DD_UTC+X_24h_HHmm_<BugType>.log`` for local time.

    依本地時間建立 ``YYYY-MM-DD_UTC+X_24h_HHmm_<BugType>.log`` 檔名。

    Args:
        bug_type: Exception class name / 例外類別名稱。
        now: Optional aware datetime (default: now) / 指定時間（預設現在）。

    Returns:
        str: File name without folder / 不含資料夾的檔名。
    """
    local_now = (now or datetime.now()).astimezone()
    offset = local_now.utcoffset()
    utc_offset_hours = int(offset.total_seconds() // 3600) if offset else 0
    tz_str = (
        f"UTC+{utc_offset_hours}" if utc_offset_hours >= 0
        else f"UTC{utc_offset_hours}"
    )
    timestamp_str = local_now.strftime(f"%Y-%m-%d_{tz_str}_24h_%H%M")
    safe_type = "".join(c if c.isalnum() or c in "_-" else "_" for c in bug_type)
    return f"{timestamp_str}_{safe_type}.log"


def setup_logger(bug_type: str = "GeneralError") -> Tuple[logging.Logger, str]:
    """Configures a logger that writes one auto-named log file.

    設定並返回具有自動生成日誌檔案功能的 Logger 實例。

    Args:
        bug_type: Exception class name used in the file name.
            用於建立日誌檔名的異常類別名稱。

    Returns:
        Tuple[logging.Logger, str]: (logger, log file path) / (Logger, 日誌路徑)。
    """
    log_filepath = os.path.join(get_log_dir(), build_log_filename(bug_type))

    logger = logging.getLogger("AutoBugLogger")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    # Prevent duplicate handlers / 防止重複添加處理器
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # File handler (append: several errors in the same minute share a file).
    # 檔案處理器（附加模式：同一分鐘同類錯誤寫入同一檔案）。
    file_handler = logging.FileHandler(log_filepath, mode="a", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Console handler for real-time output / 控制台即時輸出處理器
    console_handler = WinSafeStreamHandler(sys.stderr)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    return logger, log_filepath


def format_exception_report(
    exc_type: Type[BaseException],
    exc_value: BaseException,
    exc_traceback: Optional[TracebackType],
) -> str:
    """Formats a bilingual report with exact file/line/function/code.

    產生包含精確檔名、行號、函式與程式碼的雙語錯誤報告。

    Args:
        exc_type: Exception type / 異常型態。
        exc_value: Exception instance / 異常實例。
        exc_traceback: Traceback object / 追蹤物件。

    Returns:
        str: Report text / 報告文字。
    """
    tb_list = traceback.extract_tb(exc_traceback)
    if tb_list:
        last_frame = tb_list[-1]
        filename: str = last_frame.filename
        line_no: int = last_frame.lineno or -1
        func_name: str = last_frame.name
        code_text: str = last_frame.line or "N/A"
    else:
        filename, line_no, func_name, code_text = "Unknown", -1, "Unknown", "N/A"
    full_tb = "".join(
        traceback.format_exception(exc_type, exc_value, exc_traceback)
    )
    return (
        "\n==================== EXCEPTION DETECTED / 偵測到異常 ====================\n"
        f"Bug Type / 錯誤類型: {exc_type.__name__}\n"
        f"File Path / 檔案路徑: {filename}\n"
        f"Line Number / 錯誤行號: {line_no}\n"
        f"Function / 函式名稱: {func_name}\n"
        f"Failed Code / 異常程式碼: {code_text}\n"
        f"Detail Message / 詳細說明: {exc_value}\n"
        "----------------------------------------------------------------------\n"
        "Full Traceback / 完整追蹤訊息:\n"
        f"{full_tb}"
        "======================================================================\n"
    )


def log_exception(
    exc_type: Type[BaseException],
    exc_value: BaseException,
    exc_traceback: Optional[TracebackType],
) -> str:
    """Logs an exception to its own auto-named file and notifies listeners.

    將例外寫入自動命名的日誌檔，並通知監聽者（如 GUI 面板）。

    Args:
        exc_type: Exception type / 異常型態。
        exc_value: Exception instance / 異常實例。
        exc_traceback: Traceback object / 追蹤物件。

    Returns:
        str: Generated log file path / 生成的日誌檔路徑。
    """
    logger, log_path = setup_logger(bug_type=exc_type.__name__)
    report = format_exception_report(exc_type, exc_value, exc_traceback)
    logger.error(report)
    for handler in list(logger.handlers):
        handler.flush()
    for listener in list(_exception_listeners):
        try:
            listener(report, log_path)
        except Exception:  # pylint: disable=broad-except
            # Never let a listener break error logging.
            # 監聽者出錯時不可影響錯誤記錄本身。
            pass
    return log_path


def log_current_exception() -> str:
    """Logs the exception currently being handled (use inside ``except``).

    記錄目前正在處理的例外（於 ``except`` 區塊內呼叫）。

    Returns:
        str: Generated log file path / 生成的日誌檔路徑。
    """
    exc_type, exc_value, exc_tb = sys.exc_info()
    if exc_type is None or exc_value is None:
        raise RuntimeError("No active exception / 目前沒有正在處理的例外")
    return log_exception(exc_type, exc_value, exc_tb)


def add_exception_listener(listener: Callable[[str, str], None]) -> None:
    """Registers ``listener(report, log_path)`` called after each logged error.

    註冊監聽函式 ``listener(report, log_path)``，每次記錄例外後呼叫。

    Args:
        listener: Callback / 回呼函式。
    """
    if listener not in _exception_listeners:
        _exception_listeners.append(listener)


def remove_exception_listener(listener: Callable[[str, str], None]) -> None:
    """Unregisters a listener / 取消註冊監聽函式。

    Args:
        listener: Callback previously added / 先前註冊的回呼函式。
    """
    if listener in _exception_listeners:
        _exception_listeners.remove(listener)


def global_uncaught_exception_handler(
    exc_type: Type[BaseException],
    exc_value: BaseException,
    exc_traceback: Optional[TracebackType],
) -> None:
    """Global hook for unhandled exceptions (CLI, macro and Qt event loop).

    全域未捕獲異常鉤子（適用於 CLI、巨集與 Qt 事件迴圈）。

    Args:
        exc_type: Exception type / 異常型態。
        exc_value: Exception instance / 異常實例。
        exc_traceback: Traceback object / 追蹤物件。
    """
    if issubclass(exc_type, KeyboardInterrupt):
        # Allow standard Ctrl+C behaviour / 允許標準的 Ctrl+C 中斷行為
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    log_path = log_exception(exc_type, exc_value, exc_traceback)
    alert = _console_text(
        "\n[ALERT / 警告] Unhandled exception occurred! / 發生未捕獲異常！\n"
        f"Log saved to / 日誌已儲存至: {log_path}\n"
    )
    if not _write_console_unicode(alert, stderr=True):
        print(alert, file=sys.stderr, end="")


def install_global_hook() -> None:
    """Installs ``global_uncaught_exception_handler`` as ``sys.excepthook``.

    將 ``global_uncaught_exception_handler`` 註冊為 ``sys.excepthook``。

    Note: With PySide6 the Qt event loop routes exceptions raised inside slots
    to ``sys.excepthook``, so this one hook covers GUI callbacks as well; the
    GUI adds a listener to show the report in the Logger panel.
    注意：PySide6 會把 slot 內未捕獲的例外轉交 ``sys.excepthook``，因此同一個
    鉤子也涵蓋 GUI 事件；GUI 另外註冊監聽者把報告顯示在 Logger 面板。
    """
    sys.excepthook = global_uncaught_exception_handler


def get_app_logger() -> logging.Logger:
    """Returns the application info logger (console + GUI handlers).

    傳回應用程式一般訊息 Logger（主控台與 GUI 處理器）。

    Returns:
        logging.Logger: Logger named ``viewer`` / 名為 ``viewer`` 的 Logger。
    """
    logger = logging.getLogger(APP_LOGGER_NAME)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = WinSafeStreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
        logger.addHandler(handler)
        logger.propagate = False
    return logger
