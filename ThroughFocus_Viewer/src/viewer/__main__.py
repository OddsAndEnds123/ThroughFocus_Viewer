"""python -m viewer [image ...] / 啟動 ThroughFocus_Viewer。"""

from __future__ import annotations

import sys


if __name__ == "__main__":
    # UTF-8 console before any log line / 在任何日誌輸出前先設 UTF-8 主控台
    from viewer.app_logger import configure_windows_console
    configure_windows_console()
    from viewer.gui.main_window import main
    raise SystemExit(main(sys.argv[1:]))
