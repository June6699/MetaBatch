from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from .runtime import get_app_data_dir


def get_logs_dir() -> Path:
    logs_dir = get_app_data_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def make_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def make_log_path(prefix: str = "metabatch") -> Path:
    return get_logs_dir() / f"{prefix}_{make_timestamp()}.log"


def format_log_line(message: str) -> str:
    return f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"


class RunLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._handle = path.open("a", encoding="utf-8", newline="\n")

    def log(self, message: str) -> str:
        line = format_log_line(message)
        with self._lock:
            self._handle.write(line + "\n")
            self._handle.flush()
        return line

    def close(self) -> None:
        with self._lock:
            if not self._handle.closed:
                self._handle.close()
