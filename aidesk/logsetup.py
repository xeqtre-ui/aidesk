"""Error logging — writes crashes to %APPDATA%\\aidesk\\aidesk.log.

PyQt6 closes the app instantly on an uncaught exception. By installing our own
excepthook, the error is logged and the app keeps running.
"""
from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler

from .config import CONFIG_DIR

LOG_FILE = CONFIG_DIR / "aidesk.log"
log = logging.getLogger("aidesk")


def setup_logging() -> None:
    handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if sys.stderr is not None:  # in .exe (windowed) mode there is no stderr
        root.addHandler(logging.StreamHandler())

    def _hook(exc_type, exc, tb):
        log.error("Uncaught error", exc_info=(exc_type, exc, tb))

    def _thread_hook(args):
        log.error("Error in thread", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = _hook
    threading.excepthook = _thread_hook
    log.info("aidesk started")
