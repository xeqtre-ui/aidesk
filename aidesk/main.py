"""aidesk giriş noktası.

- Tek kopya çalışır: uygulama zaten açıksa ikinci açılış sadece menüyü gösterir.
- İlk çalıştırmada ayarlar penceresi açılır (kapatılsa bile uygulama tepside kalır).
- Global kısayollar: menü ve sesli komut.
- Hatalar %APPDATA%\\aidesk\\aidesk.log dosyasına yazılır, uygulama çökmez.
"""
from __future__ import annotations

import logging
import sys

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication

from . import config
from .logsetup import setup_logging

log = logging.getLogger("aidesk")
INSTANCE_NAME = "aidesk-single-instance"


class HotkeyBridge(QObject):
    """keyboard kütüphanesinin iş parçacığından GUI'ye sinyal taşır."""

    open_requested = pyqtSignal()
    voice_requested = pyqtSignal()


def register_hotkeys(bridge: HotkeyBridge, settings: config.Settings) -> bool:
    try:
        import keyboard

        keyboard.add_hotkey(settings.hotkey, bridge.open_requested.emit)
        keyboard.add_hotkey(settings.voice_hotkey, bridge.voice_requested.emit)
        return True
    except Exception:  # noqa: BLE001
        log.warning("Global kısayol kaydedilemedi", exc_info=True)
        return False


def _notify_running_instance() -> bool:
    """Çalışan bir kopya varsa ona 'menüyü aç' der ve True döner."""
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_NAME)
    if sock.waitForConnected(300):
        sock.write(b"open")
        sock.flush()
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return True
    return False


def _selftest() -> int:
    """`aidesk.exe --selftest`: paketlenmiş uygulamada tüm parçaları dener,
    sonucu %APPDATA%\\aidesk\\selftest.txt dosyasına yazar."""
    import importlib
    import traceback

    lines, ok = [], True
    for mod in (
        "PyQt6.QtWidgets", "anthropic", "openai", "google.genai", "keyboard",
        "pyautogui", "psutil", "pygetwindow", "pyperclip", "winsdk.windows.media.control",
        "sounddevice", "numpy", "faster_whisper", "ctranslate2", "cryptography.fernet",
        "aidesk.ui", "aidesk.voice", "aidesk.providers.anthropic_provider",
        "aidesk.providers.openai_provider", "aidesk.providers.gemini_provider",
    ):
        try:
            importlib.import_module(mod)
            lines.append(f"OK   {mod}")
        except Exception as e:  # noqa: BLE001
            ok = False
            lines.append(f"HATA {mod}: {e!r}")
    try:
        from . import tools

        tools.load_all()
        lines.append(f"OK   araçlar: {len(tools.schema())}")
        lines.append("OK   medya: " + tools.execute("now_playing", {}).splitlines()[0])
    except Exception:  # noqa: BLE001
        ok = False
        lines.append("HATA araçlar: " + traceback.format_exc())
    try:
        import numpy as np

        from .voice import SpeechToText

        stt = SpeechToText(config.load_settings().whisper_model, "tr")
        stt.preload()
        noise = (np.random.default_rng(0).standard_normal(16000 * 2) * 0.01).astype(np.float32)
        stt.transcribe(noise)  # VAD (onnx) + ctranslate2 yolunu çalıştırır
        lines.append(f"OK   whisper ({stt.model_size}) yüklendi ve çalıştı")
    except Exception:  # noqa: BLE001
        ok = False
        lines.append("HATA whisper: " + traceback.format_exc())
    lines.append("SONUÇ: " + ("HEPSİ ÇALIŞIYOR" if ok else "HATA VAR"))
    (config.CONFIG_DIR / "selftest.txt").write_text("\n".join(lines), "utf-8")
    return 0 if ok else 1


def main() -> int:
    setup_logging()
    if "--selftest" in sys.argv:
        return _selftest()
    app = QApplication(sys.argv)
    app.setApplicationName("aidesk")
    app.setQuitOnLastWindowClosed(False)

    if _notify_running_instance():
        log.info("Zaten çalışıyor; mevcut kopyaya haber verildi.")
        return 0

    from .ui import AppController, SetupDialog, app_icon, make_tray

    app.setWindowIcon(app_icon())

    server = QLocalServer()
    QLocalServer.removeServer(INSTANCE_NAME)  # önceki çökmeden kalan kilidi temizle
    server.listen(INSTANCE_NAME)

    settings = config.load_settings()
    if not config.is_configured():
        SetupDialog(settings).exec()
        settings = config.load_settings()

    ctrl = AppController(settings)
    tray = make_tray(app, ctrl)

    def _on_new_connection() -> None:
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.disconnectFromServer()
        ctrl.open_menu()

    server.newConnection.connect(_on_new_connection)

    bridge = HotkeyBridge()
    bridge.open_requested.connect(ctrl.open_menu)
    bridge.voice_requested.connect(lambda: ctrl.start_voice())
    ok = register_hotkeys(bridge, settings)

    ctrl.preload_voice()  # ilk sesli komut beklemesin

    if not config.is_configured():
        tray.showMessage("aidesk", "API anahtarı girilmedi. Tepsi ikonu > Ayarlar.")
    elif ok:
        tray.showMessage("aidesk hazır", f"{settings.hotkey}: menü  ·  {settings.voice_hotkey}: sesli komut")
    else:
        tray.showMessage("aidesk hazır", "Kısayol kaydedilemedi; tepsi ikonuna tıklayarak açın.")

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
