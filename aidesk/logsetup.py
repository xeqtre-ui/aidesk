"""Hata kaydı — çökmeleri %APPDATA%\\aidesk\\aidesk.log dosyasına yazar.

PyQt6, yakalanmamış bir istisnada uygulamayı anında kapatır. Kendi
excepthook'umuzu kurunca hata loglanır ve uygulama çalışmaya devam eder.
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
    if sys.stderr is not None:  # .exe (windowed) modunda stderr yoktur
        root.addHandler(logging.StreamHandler())

    def _hook(exc_type, exc, tb):
        log.error("Yakalanmamış hata", exc_info=(exc_type, exc, tb))

    def _thread_hook(args):
        log.error("İş parçacığında hata", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = _hook
    threading.excepthook = _thread_hook
    log.info("aidesk başlatıldı")
