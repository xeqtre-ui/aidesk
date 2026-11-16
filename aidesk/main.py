"""aidesk entry point.

- Runs as a single instance: if the app is already open, a second launch just shows the menu.
- On first run the settings window opens (even if closed, the app stays in the tray).
- Global shortcuts: menu and voice command.
- Errors are written to %APPDATA%\\aidesk\\aidesk.log; the app doesn't crash.
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
    """Carries a signal from the keyboard library's thread to the GUI."""

    open_requested = pyqtSignal()
    voice_requested = pyqtSignal()


def register_hotkeys(bridge: HotkeyBridge, settings: config.Settings) -> bool:
    try:
        import keyboard

        keyboard.add_hotkey(settings.hotkey, bridge.open_requested.emit)
        keyboard.add_hotkey(settings.voice_hotkey, bridge.voice_requested.emit)
        return True
    except Exception:  # noqa: BLE001
        log.warning("Could not register global shortcut", exc_info=True)
        return False


def _notify_running_instance() -> bool:
    """If a running instance exists, tells it to 'open the menu' and returns True."""
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
    """`aidesk.exe --selftest`: tries all parts in the packaged app and writes the
    result to %APPDATA%\\aidesk\\selftest.txt."""
    import importlib
    import traceback

    lines, ok = [], True
    for mod in (
        "PyQt6.QtWidgets", "anthropic", "openai", "google.genai", "keyboard",
        "pyautogui", "psutil", "pygetwindow", "pyperclip", "winsdk.windows.media.control",
        "sounddevice", "numpy", "faster_whisper", "ctranslate2", "cryptography.fernet",
        "aidesk.ui", "aidesk.voice", "aidesk.providers.anthropic_provider",
        "aidesk.providers.openai_provider", "aidesk.providers.gemini_provider",
        "aidesk.settings", "aidesk.orb", "aidesk.tts", "aidesk.permissions",
        "winsdk.windows.media.speechsynthesis", "winsdk.windows.storage.streams",
        "aidesk.wake", "aidesk.intents", "aidesk.tools.spotify_search", "uiautomation",
        "aidesk.context", "aidesk.memory", "aidesk.keycheck", "aidesk.tools.web", "aidesk.tools.vision",
        "aidesk.cli", "aidesk.workspace", "aidesk.cli_install",
    ):
        try:
            importlib.import_module(mod)
            lines.append(f"OK   {mod}")
        except Exception as e:  # noqa: BLE001
            ok = False
            lines.append(f"FAIL {mod}: {e!r}")
    try:
        from . import tools

        tools.load_all()
        lines.append(f"OK   tools: {len(tools.schema())}")
        lines.append("OK   media: " + tools.execute("now_playing", {}).splitlines()[0])
    except Exception:  # noqa: BLE001
        ok = False
        lines.append("FAIL tools: " + traceback.format_exc())
    try:
        import numpy as np

        from .voice import SpeechToText

        stt = SpeechToText(config.load_settings().whisper_model, "tr")
        stt.preload()
        noise = (np.random.default_rng(0).standard_normal(16000 * 2) * 0.01).astype(np.float32)
        stt.transcribe(noise)  # exercises the VAD (onnx) + ctranslate2 path
        lines.append(f"OK   whisper ({stt.model_size}) loaded and ran")
    except Exception:  # noqa: BLE001
        ok = False
        lines.append("FAIL whisper: " + traceback.format_exc())
    try:
        from .tts import Speaker

        audio, sr = Speaker().synthesize("Merhaba, ben aidesk.")  # synthesize without playing
        if len(audio) < sr * 0.3:
            raise RuntimeError("audio too short")
        lines.append(f"OK   Jarvis voice ({len(audio) / sr:.1f} s synthesized)")
    except Exception:  # noqa: BLE001
        ok = False
        lines.append("FAIL Jarvis voice: " + traceback.format_exc())
    try:
        from .wake import BUILTIN, _import_openwakeword

        _, Model = _import_openwakeword()
        for name in BUILTIN:
            Model(wakeword_models=[name], inference_framework="onnx")   # embedded model files
        lines.append(f"OK   wake word models: {', '.join(BUILTIN.values())}")
    except Exception:  # noqa: BLE001
        ok = False
        lines.append("FAIL wake word: " + traceback.format_exc())
    try:
        import uiautomation as auto

        with auto.UIAutomationInitializerInThread():
            auto.GetRootControl().GetChildren()      # are the COM wrappers working
        from .intents import match

        assert match("Tarkan Kuzu Kuzu şarkısını aç").tool == "play_song"
        lines.append("OK   Spotify song search backend (UI Automation)")
    except Exception:  # noqa: BLE001
        ok = False
        lines.append("FAIL Spotify song search: " + traceback.format_exc())
    lines.append("RESULT: " + ("ALL WORKING" if ok else "HAS ERRORS"))
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
        log.info("Already running; notified the existing instance.")
        return 0

    from .ui import AppController, SetupDialog, app_icon, make_tray

    app.setWindowIcon(app_icon())

    server = QLocalServer()
    QLocalServer.removeServer(INSTANCE_NAME)  # clear a lock left over from a previous crash
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
    bridge.voice_requested.connect(lambda: ctrl.voice_entry())
    ok = register_hotkeys(bridge, settings)

    ctrl.preload_voice()
    ctrl.start_wake()      # start listening for "Hey Jarvis" if enabled in settings  # so the first voice command isn't delayed

    if not config.is_configured():
        tray.showMessage("aidesk", "No API key entered. Tray icon > Settings.")
    elif ok:
        tray.showMessage("aidesk ready", f"{settings.hotkey}: menu  ·  {settings.voice_hotkey}: voice command")
    else:
        tray.showMessage("aidesk ready", "Could not register the shortcut; open it by clicking the tray icon.")

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
