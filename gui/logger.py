"""GUI logging with colored levels, timestamps, and thread info.

Usage:
    from gui.logger import log
    log.info("Engine started")
    log.warning("Slow frame: 200ms")
    log.error("Engine crashed")
    log.debug("Bestmove received: e2e4")
"""

import sys
import time
import threading

# ANSI color codes
_COLORS = {
    "DEBUG": "\033[36m",  # cyan
    "INFO": "\033[32m",  # green
    "WARN": "\033[33m",  # yellow
    "ERROR": "\033[31m",  # red
    "RESET": "\033[0m",
}

_LEVEL_ORDER = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3}
_MIN_LEVEL = "INFO"
_START_TIME = time.monotonic()


class _Logger:
    def __init__(self):
        self.min_level = _LEVEL_ORDER[_MIN_LEVEL]

    def set_level(self, level: str):
        self.min_level = _LEVEL_ORDER.get(level.upper(), 0)

    def _emit(self, level: str, msg: str):
        if _LEVEL_ORDER.get(level, 0) < self.min_level:
            return
        elapsed = time.monotonic() - _START_TIME
        tid = threading.current_thread().name
        if tid == "MainThread":
            tid = "Main"
        color = _COLORS.get(level, "")
        reset = _COLORS["RESET"]
        line = f"{color}[{elapsed:8.3f}] " f"{level:<5s}{reset} " f"[{tid}] {msg}"
        print(line, file=sys.stderr, flush=True)

    def debug(self, msg: str):
        self._emit("DEBUG", msg)

    def info(self, msg: str):
        self._emit("INFO", msg)

    def warning(self, msg: str):
        self._emit("WARN", msg)

    def error(self, msg: str):
        self._emit("ERROR", msg)

    def timed(self, label: str):
        """Context manager that logs duration at INFO level if >50ms, DEBUG otherwise."""
        return _TimedContext(self, label)


class _TimedContext:
    def __init__(self, logger, label):
        self.logger = logger
        self.label = label

    def __enter__(self):
        self.t0 = time.monotonic()
        return self

    def __exit__(self, *exc):
        dt = (time.monotonic() - self.t0) * 1000
        if dt > 200:
            self.logger.warning(f"{self.label}: {dt:.0f}ms")
        elif dt > 50:
            self.logger.info(f"{self.label}: {dt:.0f}ms")
        else:
            self.logger.debug(f"{self.label}: {dt:.1f}ms")


log = _Logger()
