"""PyInstaller 运行时钩子：全局崩溃兜底（在主脚本之前执行）。

职责：
  1. 安装 sys.excepthook，捕获任何未处理异常（含启动期 ``PySide6`` /
     QtCore DLL 加载失败 —— 该异常发生在主脚本的 import 阶段，晚于本钩子）。
  2. 把完整堆栈写入 exe 同级的 ``logs/metabatch_crash_*.log``。
  3. 优先用已加载的 PySide6 弹窗；若 Qt 本身不可用则退化为 Win32 原生弹窗。
  4. 立即结束进程，避免 PyInstaller 再弹出原始的
     "Unhandled exception in script" 对话框。

本钩子只使用标准库，不依赖项目包，确保在最早、最脆弱的启动阶段也能运行。
"""

from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime


def _crash_log_dir() -> str:
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.getcwd()
    logs_dir = os.path.join(base, "logs")
    try:
        os.makedirs(logs_dir, exist_ok=True)
    except OSError:
        pass
    return logs_dir


def _show_with_qt(title: str, text: str) -> bool:
    """若 Qt 事件循环已存在则用 QMessageBox；否则返回 False 交给原生弹窗。"""
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        if QApplication.instance() is None:
            return False
        QMessageBox.critical(None, title, text)
        return True
    except Exception:
        return False


def _show_native(title: str, text: str) -> None:
    if os.name == "nt":
        try:
            import ctypes

            # MB_OK = 0x0, MB_ICONERROR = 0x10
            ctypes.windll.user32.MessageBoxW(0, text, title, 0x0 | 0x10)
            return
        except Exception:
            pass
    print("\n" + title + "\n" + text)


def _excepthook(exc_type, exc_value, exc_tb) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    now = datetime.now()
    detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))

    log_path = os.path.join(
        _crash_log_dir(),
        "metabatch_crash_" + now.strftime("%Y%m%d_%H%M%S") + ".log",
    )
    header = (
        "MetaBatch 崩溃日志\n"
        "时间: " + now.strftime("%Y-%m-%d %H:%M:%S") + "\n"
        "Python: " + sys.version.replace("\n", " ") + "\n"
        "平台: " + sys.platform + "\n"
        + "=" * 50 + "\n\n"
    )
    try:
        with open(log_path, "w", encoding="utf-8") as handle:
            handle.write(header + detail)
    except OSError:
        log_path = "(日志写入失败)"

    # 控制台（如有）输出一份
    print(detail)

    title = "MetaBatch 运行出错"
    message = (
        "程序发生未预期错误，已自动保存日志。\n\n"
        "日志路径:\n" + log_path + "\n\n"
        "错误信息:\n" + str(exc_value)
    )

    if not _show_with_qt(title, message):
        _show_native(title, message)

    # 立即终止，阻止 PyInstaller 弹出原始错误框
    try:
        os._exit(1)
    except Exception:
        sys.exit(1)


sys.excepthook = _excepthook
