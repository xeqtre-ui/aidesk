"""Configuration and secure API key storage.

API keys are stored in the user's AppData folder, encrypted with a key derived
per machine. They are never written to disk as plain text.
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# ----------------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------------
APP_NAME = "aidesk"


def _base_dir() -> Path:
    """Platform-appropriate configuration directory."""
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = root / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


CONFIG_DIR = _base_dir()
CONFIG_FILE = CONFIG_DIR / "config.json"
SECRETS_FILE = CONFIG_DIR / "secrets.enc"
SALT_FILE = CONFIG_DIR / "salt.bin"


# ----------------------------------------------------------------------------
# Encryption helpers
# ----------------------------------------------------------------------------
def _machine_passphrase() -> bytes:
    """Produces a roughly stable, machine-bound passphrase.

    Note: this is not against sophisticated attackers; it is to keep the keys
    from sitting on disk as plain text. If stronger protection is wanted, a
    master password could be taken from the user and added here.
    """
    parts = [
        os.environ.get("COMPUTERNAME", ""),
        os.environ.get("USERNAME", os.environ.get("USER", "")),
        str(Path.home()),
    ]
    return ("::".join(parts) or "aidesk-fallback").encode("utf-8")


def _get_salt() -> bytes:
    if SALT_FILE.exists():
        return SALT_FILE.read_bytes()
    salt = os.urandom(16)
    SALT_FILE.write_bytes(salt)
    return salt


def _fernet() -> Fernet:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_get_salt(),
        iterations=390_000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(_machine_passphrase()))
    return Fernet(key)


# ----------------------------------------------------------------------------
# Secrets (API keys)
# ----------------------------------------------------------------------------
def load_secrets() -> dict[str, str]:
    if not SECRETS_FILE.exists():
        return {}
    try:
        data = _fernet().decrypt(SECRETS_FILE.read_bytes())
        return json.loads(data.decode("utf-8"))
    except (InvalidToken, ValueError, json.JSONDecodeError):
        # If it can't be decrypted (e.g. the machine changed) return empty.
        return {}


def save_secrets(secrets: dict[str, str]) -> None:
    blob = _fernet().encrypt(json.dumps(secrets).encode("utf-8"))
    SECRETS_FILE.write_bytes(blob)
    # User-only access (effective on POSIX).
    try:
        os.chmod(SECRETS_FILE, 0o600)
    except OSError:
        pass


def get_api_key(provider: str) -> str | None:
    return load_secrets().get(f"{provider}_api_key")


def set_api_key(provider: str, key: str) -> None:
    s = load_secrets()
    s[f"{provider}_api_key"] = key.strip()
    save_secrets(s)


# ----------------------------------------------------------------------------
# Config (non-sensitive settings)
# ----------------------------------------------------------------------------
@dataclass
class Settings:
    provider: str = "anthropic"            # anthropic | openai | gemini
    model: dict[str, str] = field(default_factory=lambda: {
        "anthropic": "claude-sonnet-5-5",
        "openai": "gpt-5-mini",
        "gemini": "gemini-3.5-flash",
    })
    hotkey: str = "ctrl+space"             # open the menu
    voice_hotkey: str = "ctrl+shift+space" # voice command
    stt_mode: str = "auto"                 # auto (cloud if available) | cloud | local
    mic_name: str = ""                     # empty = automatic (built-in mic first)
    whisper_model: str = "base"            # local model: tiny|base|small|medium (base: fast)
    language: str = "tr"
    require_confirmation: bool = True      # old setting; replaced by permission_mode
    max_tool_iterations: int = 12
    # --- Jarvis (voice conversation) ---
    jarvis_enabled: bool = False           # voice command = orb in the center + spoken reply
    jarvis_continuous: bool = True         # keep listening after an answer
    jarvis_idle_close: int = 60            # close after this many s of silence (0 = only with "görüşürüz")
    tts_engine: str = "windows"            # windows | openai
    tts_voice: str = ""                    # empty = first voice matching the language (e.g. Microsoft Tolga)
    tts_rate: float = 1.1
    orb_x: int = -10000                    # -10000 = center of the screen
    orb_y: int = -10000
    orb_scale: float = 1.0
    # --- Wake word ---
    wake_enabled: bool = False
    wake_word: str = "hey_jarvis"          # hey_jarvis | alexa | hey_mycroft | custom
    wake_phrase: str = "hey asistan"       # when wake_word == "custom"
    wake_sensitivity: str = "normal"       # low | normal | high
    # --- Permissions ---
    permission_mode: str = "standard"      # standard | full | custom
    permissions: dict[str, str] = field(default_factory=dict)  # custom: category -> allow/ask/deny

    def active_model(self) -> str:
        return self.model.get(self.provider, "")

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Settings":
        base = cls()
        for k, v in d.items():
            if k == "model" and isinstance(v, dict):
                # Keep old saved models, fill missing providers with the default.
                # Old defaults (retired) -> current default
                if v.get("gemini") in ("gemini-1.5-pro", "gemini-2.5-flash") or \
                        str(v.get("gemini", "")).endswith("-lite"):   # lite is only a temporary fallback
                    v = {**v, "gemini": base.model["gemini"]}
                if v.get("openai") == "gpt-4o":            # old default
                    v = {**v, "openai": base.model["openai"]}
                if v.get("anthropic") == "claude-opus-4-8":
                    v = {**v, "anthropic": base.model["anthropic"]}
                base.model = {**base.model, **v}
            elif k == "max_tool_iterations":
                base.max_tool_iterations = max(12, int(v))   # the old limit of 8 wasn't enough for research
            elif hasattr(base, k):
                setattr(base, k, v)
        # If the old "require confirmation" is off and no permission mode was ever set: Full Access
        if d.get("require_confirmation") is False and "permission_mode" not in d:
            base.permission_mode = "full"
        return base


def load_settings() -> Settings:
    if CONFIG_FILE.exists():
        try:
            return Settings.from_dict(json.loads(CONFIG_FILE.read_text("utf-8")))
        except (ValueError, json.JSONDecodeError):
            pass
    return Settings()


def save_settings(s: Settings) -> None:
    CONFIG_FILE.write_text(json.dumps(s.to_dict(), indent=2), "utf-8")


def is_configured() -> bool:
    """Is there an API key for at least one provider?"""
    secrets = load_secrets()
    return any(k.endswith("_api_key") and v for k, v in secrets.items())
