# -*- mode: python ; coding: utf-8 -*-
# aidesk package: windowed app (aidesk.exe) + terminal mode (aidesk-cli.exe),
# with shared libraries in a single folder. Build: .\build.ps1
import os
from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
datas, binaries, hidden = [], [], []
for pkg in ("faster_whisper", "ctranslate2", "onnxruntime", "av", "winsdk", "uiautomation", "comtypes"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hidden += h
datas += collect_data_files("openwakeword")
hidden += ["openwakeword.model", "openwakeword.utils", "pygetwindow", "pyperclip", "keyboard"]

a = Analysis(
    [os.path.join(ROOT, "run_aidesk.py"), os.path.join(ROOT, "run_aidesk_cli.py")],
    pathex=[ROOT],
    datas=datas,
    binaries=binaries,
    hiddenimports=hidden,
    excludes=["tkinter", "matplotlib", "google.generativeai", "googleapiclient", "scipy", "sklearn"],
)
pyz = PYZ(a.pure)
icon = os.path.join(ROOT, "assets", "aidesk.ico")
gui = EXE(pyz, [s for s in a.scripts if s[0] != "run_aidesk_cli"], [], exclude_binaries=True,
          name="aidesk", console=False, icon=icon)
cli = EXE(pyz, [s for s in a.scripts if s[0] != "run_aidesk"], [], exclude_binaries=True,
          name="aidesk-cli", console=True, icon=icon)
coll = COLLECT(gui, cli, a.binaries, a.datas, name="aidesk")
