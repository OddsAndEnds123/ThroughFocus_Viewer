"""Qt log bridge / Qt 日誌橋接。"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from viewer.path_display import redact_paths_in_text


class LogBridge(QObject):
    """Thread-safe bridge from logging to the GUI / logging 到 GUI 的橋接。"""

    message = Signal(str)
    exception = Signal(str, str)


class QtLogHandler(logging.Handler):
    """logging handler that forwards records to a Qt signal."""

    def __init__(self, bridge: LogBridge) -> None:
        super().__init__(logging.INFO)
        self.bridge = bridge
        self.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # Strip home-dir absolute paths before GUI shows them /
            # 進 GUI 前去掉家目錄絕對路徑個資
            text = redact_paths_in_text(self.format(record))
            self.bridge.message.emit(text)
        except RuntimeError:
            pass
