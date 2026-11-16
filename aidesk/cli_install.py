"""Installs / removes the `aidesk` command in PowerShell (used by the button in Settings).

A `bin\\aidesk.cmd` is written into the app folder and this `bin` folder is added to
the USER PATH (the system PATH is untouched, no admin rights needed). It takes effect
in newly opened terminals.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]          # repo root when running from source


def bin_dir() -> Path:
    return app_dir() / "bin"


def _shim_text() -> str:
    if getattr(sys, "frozen", False):
        return '@echo off\r\n"%~dp0..\\aidesk-cli.exe" %*\r\n'
    py = Path(sys.executable).resolve()
    return (f'@echo off\r\nset "PYTHONPATH={app_dir()};%PYTHONPATH%"\r\n'
            f'"{py}" -m aidesk.cli %*\r\n')


def _user_path() -> str:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
        try:
            return winreg.QueryValueEx(k, "Path")[0]
        except FileNotFoundError:
            return ""


def _set_user_path(value: str) -> None:
    import ctypes
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "Path", 0, winreg.REG_EXPAND_SZ, value)
    # Notify open programs (Explorer etc.) that the environment variable changed
    HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x001A, 0x0002
    ctypes.windll.user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
                                             SMTO_ABORTIFHUNG, 3000, None)


def _entries(path_value: str) -> list[str]:
    return [p for p in path_value.split(";") if p.strip()]


def is_installed() -> bool:
    if os.name != "nt":
        return False
    target = os.path.normcase(str(bin_dir()))
    return (bin_dir() / "aidesk.cmd").exists() and any(
        os.path.normcase(os.path.expandvars(p).rstrip("\\")) == target for p in _entries(_user_path()))


def install() -> str:
    b = bin_dir()
    b.mkdir(exist_ok=True)
    (b / "aidesk.cmd").write_text(_shim_text(), "utf-8")
    entries = _entries(_user_path())
    if not any(os.path.normcase(os.path.expandvars(p).rstrip("\\")) == os.path.normcase(str(b)) for p in entries):
        _set_user_path(";".join(entries + [str(b)]))
    return (f"Installed. Open a NEW PowerShell window and type 'aidesk' in any folder.\n"
            f"(Folder added: {b})")


def uninstall() -> str:
    b = os.path.normcase(str(bin_dir()))
    entries = _entries(_user_path())
    keep = [p for p in entries if os.path.normcase(os.path.expandvars(p).rstrip("\\")) != b]
    if len(keep) != len(entries):
        _set_user_path(";".join(keep))
    return "Terminal command removed (takes effect in new terminals)."
