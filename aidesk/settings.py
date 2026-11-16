"""Settings window — General, Voice and Jarvis, Permissions tabs."""
from __future__ import annotations

import logging
import threading

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import config, permissions

log = logging.getLogger("aidesk.settings")

OPENAI_VOICES = ["onyx", "ash", "echo", "alloy", "ballad", "coral", "sage", "shimmer", "verse"]
FULL_ACCESS_WARNING = (
    "With Full Access on, the assistant asks for approval for NO action:\n\n"
    "• It can run PowerShell commands\n"
    "• It can type and click and press keys on your behalf\n"
    "• It can close apps and open and read files\n\n"
    "If the AI misunderstands, it may do irreversible things. "
    "Are you sure you want to enable Full Access?"
)


MUTED = "#a3b8ae"

# Tab / group / slider styles matching the app's dark green theme
EXTRA_STYLE = """
QTabWidget::pane { border: 1px solid #33463e; border-radius: 8px; top: -1px; background: #111916; }
QTabBar::tab {
    background: #182420; color: #a3b8ae; border: 1px solid #33463e; border-bottom: none;
    padding: 7px 16px; margin-right: 3px; border-top-left-radius: 7px; border-top-right-radius: 7px;
}
QTabBar::tab:selected { background: #111916; color: #a9f2ce; font-weight: 600; }
QGroupBox {
    color: #a9f2ce; font-weight: 600; border: 1px solid #33463e; border-radius: 8px;
    margin-top: 14px; padding: 12px 10px 8px;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
QRadioButton { color: #eaf4ef; font-weight: 600; spacing: 8px; }
QRadioButton::indicator, QCheckBox::indicator {
    width: 15px; height: 15px; border: 1px solid #5c7a6c; background: #182420;
}
QRadioButton::indicator { border-radius: 8px; }
QCheckBox::indicator { border-radius: 4px; }
QRadioButton::indicator:checked, QCheckBox::indicator:checked { background: #a9f2ce; border-color: #a9f2ce; }
QSlider::groove:horizontal { height: 4px; background: #33463e; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; margin: -6px 0; border-radius: 7px; background: #a9f2ce; }
QSlider::sub-page:horizontal { background: #76bd9a; border-radius: 2px; }
QComboBox:disabled { color: #6f857a; }
"""


def _hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(f"color:{MUTED}; font-size:11px; font-weight: normal;")
    return lbl


class SetupDialog(QDialog):
    def __init__(self, settings: config.Settings) -> None:
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint)
        from .ui import DIALOG_STYLE, app_icon, app_pixmap

        self.settings = settings
        self.setWindowTitle("aidesk — Settings")
        self.setWindowIcon(app_icon())
        self.setStyleSheet(DIALOG_STYLE + EXTRA_STYLE)
        self.resize(660, 760)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 16, 22, 18)
        header = QHBoxLayout()
        header.setSpacing(12)
        mark = QLabel()
        dpr = self.devicePixelRatioF()
        pm = app_pixmap(round(36 * dpr))
        pm.setDevicePixelRatio(dpr)
        mark.setPixmap(pm)
        header.addWidget(mark)
        title = QLabel("Settings")
        title.setObjectName("settingsTitle")
        header.addWidget(title, 1)
        root.addLayout(header)
        tabs = QTabWidget()
        tabs.tabBar().setUsesScrollButtons(False)
        tabs.addTab(self._tab_general(), "General")
        voice_scroll = QScrollArea()
        voice_scroll.setWidgetResizable(True)
        voice_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        voice_scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        voice_scroll.setWidget(self._tab_voice())
        tabs.addTab(voice_scroll, "Voice and Jarvis")
        tabs.addTab(self._tab_permissions(), "Permissions")
        root.addWidget(tabs)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setObjectName("settingsSave")
        save.setDefault(True)
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

    # --- General -------------------------------------------------------------
    def _tab_general(self) -> QWidget:
        from .keycheck import MODEL_SUGGESTIONS

        w = QWidget()
        form = QFormLayout(w)
        self.provider = QComboBox()
        self.provider.addItems(["anthropic", "openai", "gemini"])
        self.provider.setCurrentText(self.settings.provider)
        form.addRow("Default provider:", self.provider)

        self.model = QComboBox()
        self.model.setEditable(True)            # a model not in the list can also be typed
        self._models = dict(self.settings.model)

        def fill_models() -> None:
            prov = self.provider.currentText()
            self.model.blockSignals(True)
            self.model.clear()
            self.model.addItems(MODEL_SUGGESTIONS.get(prov, []))
            self.model.setCurrentText(self._models.get(prov, ""))
            self.model.blockSignals(False)

        self.model.currentTextChanged.connect(
            lambda t: self._models.__setitem__(self.provider.currentText(), t.strip()))
        self.provider.currentTextChanged.connect(lambda _t: fill_models())
        fill_models()
        form.addRow("Model:", self.model)

        self.keys: dict[str, QLineEdit] = {}
        self.key_status: dict[str, QLabel] = {}
        for prov, label, ph in (
            ("anthropic", "Anthropic API key:", "sk-ant-..."),
            ("openai", "OpenAI API key:", "sk-..."),
            ("gemini", "Gemini API key:", "AIza..."),
        ):
            le = QLineEdit(config.get_api_key(prov) or "")
            le.setEchoMode(QLineEdit.EchoMode.Password)
            le.setPlaceholderText(ph)
            self.keys[prov] = le
            st = QLabel("")
            st.setStyleSheet(f"color:{MUTED}; font-size:11px;")
            self.key_status[prov] = st
            col = QVBoxLayout()
            col.setSpacing(1)
            col.addWidget(le)
            col.addWidget(st)
            form.addRow(label, col)

        check = QPushButton("🔑 Check keys")
        check.clicked.connect(self._check_keys)
        form.addRow(check)

        term_row = QHBoxLayout()
        self.term_btn = QPushButton()
        self.term_status = QLabel()
        self.term_status.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        self.term_status.setWordWrap(True)
        self.term_btn.clicked.connect(self._toggle_terminal)
        term_row.addWidget(self.term_btn)
        term_row.addWidget(self.term_status, 1)
        form.addRow("Terminal mode:", term_row)
        self._refresh_terminal()

        self.hotkey = QLineEdit(self.settings.hotkey)
        form.addRow("Menu shortcut:", self.hotkey)
        self.voice_hotkey = QLineEdit(self.settings.voice_hotkey)
        form.addRow("Voice command / Jarvis shortcut:", self.voice_hotkey)
        form.addRow(_hint("Commands go to the selected provider. If that provider's quota/credit runs out, "
                          "another provider whose key is set is used automatically as a backup. "
                          "Keys are stored encrypted on this computer. Shortcut changes take effect "
                          "after a restart."))
        return w

    def _refresh_terminal(self) -> None:
        from . import cli_install

        try:
            on = cli_install.is_installed()
        except Exception:  # noqa: BLE001
            on = False
        self.term_btn.setText("⌨️ Remove terminal command" if on else "⌨️ Install terminal command (aidesk)")
        self.term_status.setText(
            "Installed: type 'aidesk' in any folder in PowerShell." if on else
            "Type 'aidesk' in any folder in PowerShell to open the terminal mode that works with "
            "files like Claude Code. Adds a folder to your user PATH.")

    def _toggle_terminal(self) -> None:
        from . import cli_install

        try:
            msg = cli_install.uninstall() if cli_install.is_installed() else cli_install.install()
            QMessageBox.information(self, "Terminal mode", msg)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Terminal mode", f"Failed: {e}")
        self._refresh_terminal()

    def _check_keys(self) -> None:
        """Tries the keys in the background; results are written to the labels."""
        from PyQt6.QtCore import QTimer

        from .keycheck import check

        results: dict[str, tuple[bool, str]] = {}
        todo = {p: le.text() for p, le in self.keys.items()}
        for prov, st in self.key_status.items():
            st.setText("checking…" if todo[prov].strip() else "")
            st.setStyleSheet(f"color:{MUTED}; font-size:11px;")

        def worker() -> None:
            for prov, key in todo.items():
                if key.strip():
                    results[prov] = check(prov, key)

        th = threading.Thread(target=worker, daemon=True)
        th.start()

        def poll() -> None:
            for prov, (ok, msg) in list(results.items()):
                st = self.key_status[prov]
                st.setText(msg)
                st.setStyleSheet(f"color:{'#a9f2ce' if ok else '#ffb4a3'}; font-size:11px;")
            if th.is_alive():
                QTimer.singleShot(250, poll)

        QTimer.singleShot(250, poll)

    # --- Voice and Jarvis ----------------------------------------------------
    def _tab_voice(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        jarvis = QGroupBox("Jarvis — talk to me by voice")
        jf = QFormLayout(jarvis)
        self.jarvis_enabled = QCheckBox("Enable voice assistant mode")
        self.jarvis_enabled.setChecked(self.settings.jarvis_enabled)
        jf.addRow(self.jarvis_enabled)
        jf.addRow(_hint("When on, the voice command shortcut opens a hologram orb in the center of the "
                        "screen; the assistant speaks its answers and the orb grows and shrinks while talking."))
        self.jarvis_continuous = QCheckBox("Keep listening after an answer (like a conversation)")
        self.jarvis_continuous.setChecked(self.settings.jarvis_continuous)
        jf.addRow(self.jarvis_continuous)
        self.jarvis_idle = QComboBox()
        for secs, label in ((15, "15 seconds"), (60, "1 minute"), (300, "5 minutes"),
                            (0, "Never — only when you say \"görüşürüz\"")):
            self.jarvis_idle.addItem(label, secs)
        self.jarvis_idle.setCurrentIndex(max(0, self.jarvis_idle.findData(self.settings.jarvis_idle_close)))
        jf.addRow("Close when silent:", self.jarvis_idle)

        self.tts_engine = QComboBox()
        self.tts_engine.addItem("Windows voice (offline, instant, free)", "windows")
        self.tts_engine.addItem("OpenAI voice (more natural, needs an OpenAI key)", "openai")
        self.tts_engine.setCurrentIndex(max(0, self.tts_engine.findData(self.settings.tts_engine)))
        self.tts_engine.currentIndexChanged.connect(self._fill_voices)
        jf.addRow("Voice engine:", self.tts_engine)
        self.tts_voice = QComboBox()
        jf.addRow("Voice:", self.tts_voice)
        self._fill_voices()

        rate_row = QHBoxLayout()
        self.tts_rate = QSlider(Qt.Orientation.Horizontal)
        self.tts_rate.setRange(70, 160)
        self.tts_rate.setValue(int(self.settings.tts_rate * 100))
        self.rate_label = QLabel()
        self.tts_rate.valueChanged.connect(lambda v: self.rate_label.setText(f"{v / 100:.1f}x"))
        self.rate_label.setText(f"{self.tts_rate.value() / 100:.1f}x")
        rate_row.addWidget(self.tts_rate)
        rate_row.addWidget(self.rate_label)
        jf.addRow("Speech rate:", rate_row)
        test = QPushButton("🔊 Test voice")
        test.clicked.connect(self._test_voice)
        jf.addRow(test)
        lay.addWidget(jarvis)

        wake = QGroupBox("Wake word")
        wf = QFormLayout(wake)
        self.wake_enabled = QCheckBox("Wake by voice (hands-free)")
        self.wake_enabled.setChecked(self.settings.wake_enabled)
        wf.addRow(self.wake_enabled)
        wf.addRow(_hint("The microphone only waits for the wake phrase in the background; the audio is "
                        "processed entirely on your computer and sent nowhere. You can also say a command "
                        "right after the phrase: \"Hey Jarvis, müziği aç\"."))
        self.wake_word = QComboBox()
        for key, label in (("hey_jarvis", "Hey Jarvis (recommended)"), ("alexa", "Alexa"),
                           ("hey_mycroft", "Hey Mycroft"), ("custom", "Custom phrase…")):
            self.wake_word.addItem(label, key)
        self.wake_word.setCurrentIndex(max(0, self.wake_word.findData(self.settings.wake_word)))
        wf.addRow("Wake phrase:", self.wake_word)
        self.wake_phrase = QLineEdit(self.settings.wake_phrase)
        self.wake_phrase.setPlaceholderText("e.g. hey asistan")
        wf.addRow("Custom phrase:", self.wake_phrase)
        self.wake_sens = QComboBox()
        for key, label in (("low", "Low — fewer false wakes"), ("normal", "Normal"),
                           ("high", "High — wakes more easily with accented/quiet speech")):
            self.wake_sens.addItem(label, key)
        self.wake_sens.setCurrentIndex(max(0, self.wake_sens.findData(self.settings.wake_sensitivity)))
        wf.addRow("Sensitivity:", self.wake_sens)

        def _sync_wake() -> None:
            on = self.wake_enabled.isChecked()
            custom = self.wake_word.currentData() == "custom"
            self.wake_word.setEnabled(on)
            self.wake_phrase.setEnabled(on and custom)
            self.wake_sens.setEnabled(on and not custom)

        self.wake_enabled.toggled.connect(_sync_wake)
        self.wake_word.currentIndexChanged.connect(_sync_wake)
        _sync_wake()
        lay.addWidget(wake)

        stt = QGroupBox("Speech recognition")
        sf = QFormLayout(stt)
        self.stt_mode = QComboBox()
        self.stt_mode.addItem("Fast — cloud (with your Gemini/OpenAI key, ~1 s)", "auto")
        self.stt_mode.addItem("Local — offline, audio never leaves your computer", "local")
        self.stt_mode.setCurrentIndex(1 if self.settings.stt_mode == "local" else 0)
        sf.addRow("Speech recognition:", self.stt_mode)
        self.mic = QComboBox()
        self.mic.addItem("Automatic (built-in mic first)", "")
        try:
            from .voice import list_microphones

            for name in list_microphones():
                self.mic.addItem(name, name)
        except Exception:  # noqa: BLE001
            log.warning("Could not get microphone list", exc_info=True)
        idx = self.mic.findData(self.settings.mic_name)
        self.mic.setCurrentIndex(idx if idx >= 0 else 0)
        sf.addRow("Microphone:", self.mic)
        self.whisper = QComboBox()
        self.whisper.addItems(["tiny", "base", "small", "medium"])
        self.whisper.setCurrentText(self.settings.whisper_model)
        sf.addRow("Local speech model:", self.whisper)
        lay.addWidget(stt)
        lay.addStretch(1)
        return w

    def _fill_voices(self) -> None:
        engine = self.tts_engine.currentData()
        self.tts_voice.clear()
        if engine == "openai":
            for v in OPENAI_VOICES:
                self.tts_voice.addItem(v, v)
        else:
            from .tts import windows_voices

            self.tts_voice.addItem("Automatic (Turkish voice)", "")
            for v in windows_voices():
                self.tts_voice.addItem(v, v)
        idx = self.tts_voice.findData(self.settings.tts_voice)
        self.tts_voice.setCurrentIndex(idx if idx >= 0 else 0)

    def _test_voice(self) -> None:
        from .tts import Speaker

        engine = self.tts_engine.currentData()
        sp = Speaker(engine=engine, voice=self.tts_voice.currentData() or "",
                     openai_key=self.keys["openai"].text().strip() or config.get_api_key("openai"),
                     rate=self.tts_rate.value() / 100)

        def _run() -> None:
            try:
                # Spoken demo phrase: kept in Turkish because the assistant's voice is Turkish.
                sp.speak("Merhaba efendim. Ben aidesk. Size nasıl yardımcı olabilirim?")
            except Exception:  # noqa: BLE001
                log.warning("Voice test failed", exc_info=True)

        threading.Thread(target=_run, daemon=True).start()

    # --- Permissions ---------------------------------------------------------
    def _tab_permissions(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.perm_group = QButtonGroup(self)
        self.perm_radios: dict[str, QRadioButton] = {}
        for key, title, desc in (
            ("standard", "Standard (recommended)", "Safe actions are free; command line, keyboard/mouse and closing apps ask for approval."),
            ("full", "Full Access", "No action asks for approval. Only enable this if you know what you're doing."),
            ("custom", "Custom", "Choose each category separately."),
        ):
            rb = QRadioButton(title)
            self.perm_group.addButton(rb)
            self.perm_radios[key] = rb
            lay.addWidget(rb)
            lay.addWidget(_hint("      " + desc))
        self._perm_mode = self.settings.permission_mode if self.settings.permission_mode in self.perm_radios else "standard"
        self.perm_radios[self._perm_mode].setChecked(True)

        box = QGroupBox("Categories")
        grid = QGridLayout(box)
        self.perm_combos: dict[str, QComboBox] = {}
        for row, (key, title, desc, _default) in enumerate(permissions.CATEGORIES):
            name = QLabel(f"<b>{title}</b><br><span style='color:{MUTED};font-size:11px'>{desc}</span>")
            name.setWordWrap(True)
            cb = QComboBox()
            for lvl in (permissions.ALLOW, permissions.ASK, permissions.DENY):
                cb.addItem(permissions.LEVEL_LABELS[lvl], lvl)
            self.perm_combos[key] = cb
            grid.addWidget(name, row, 0)
            grid.addWidget(cb, row, 1)
        grid.setColumnStretch(0, 1)
        lay.addWidget(box)
        lay.addStretch(1)

        self._custom_levels = {k: permissions.level_for(
            config.Settings(permission_mode="custom", permissions=self.settings.permissions), k)
            for k in permissions.CATEGORY_KEYS}
        for key, rb in self.perm_radios.items():
            rb.toggled.connect(lambda on, k=key: on and self._on_perm_mode(k))
        self._refresh_perm_table()
        return w

    def _on_perm_mode(self, mode: str) -> None:
        if mode == "full" and self._perm_mode != "full":
            ok = QMessageBox.warning(
                self, "Full Access", FULL_ACCESS_WARNING,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            ) == QMessageBox.StandardButton.Yes
            if not ok:
                self.perm_radios[self._perm_mode].setChecked(True)
                return
        if self._perm_mode == "custom":
            self._custom_levels = {k: cb.currentData() for k, cb in self.perm_combos.items()}
        self._perm_mode = mode
        self._refresh_perm_table()

    def _refresh_perm_table(self) -> None:
        for key, cb in self.perm_combos.items():
            if self._perm_mode == "full":
                lvl = permissions.ALLOW
            elif self._perm_mode == "standard":
                lvl = permissions.STANDARD[key]
            else:
                lvl = self._custom_levels.get(key, permissions.STANDARD[key])
            cb.setCurrentIndex(cb.findData(lvl))
            cb.setEnabled(self._perm_mode == "custom")

    # --- Save ----------------------------------------------------------------
    def showEvent(self, e) -> None:  # noqa: N802
        from .ui import force_foreground

        super().showEvent(e)
        force_foreground(self)

    def _save(self) -> None:
        for prov, le in self.keys.items():
            if le.text().strip():
                config.set_api_key(prov, le.text())
        s = self.settings
        s.provider = self.provider.currentText()
        s.model = {**s.model, **{k: v for k, v in self._models.items() if v}}
        s.hotkey = self.hotkey.text().strip() or "ctrl+space"
        s.voice_hotkey = self.voice_hotkey.text().strip() or "ctrl+shift+space"
        s.jarvis_enabled = self.jarvis_enabled.isChecked()
        s.jarvis_continuous = self.jarvis_continuous.isChecked()
        s.jarvis_idle_close = int(self.jarvis_idle.currentData())
        s.tts_engine = self.tts_engine.currentData()
        s.tts_voice = self.tts_voice.currentData() or ""
        s.tts_rate = self.tts_rate.value() / 100
        s.stt_mode = self.stt_mode.currentData()
        s.mic_name = self.mic.currentData() or ""
        s.whisper_model = self.whisper.currentText()
        s.wake_enabled = self.wake_enabled.isChecked()
        s.wake_word = self.wake_word.currentData()
        s.wake_phrase = self.wake_phrase.text().strip() or "hey asistan"
        s.wake_sensitivity = self.wake_sens.currentData()
        s.permission_mode = self._perm_mode
        if self._perm_mode == "custom":
            s.permissions = {k: cb.currentData() for k, cb in self.perm_combos.items()}
        config.save_settings(s)
        if not config.get_api_key(s.provider):
            QMessageBox.warning(self, "Missing", f"Enter an API key for the selected provider ({s.provider}).")
            return
        self.accept()
