"""Yapılandırma ve güvenli API anahtarı depolama.

API anahtarları, makineye özgü türetilmiş bir anahtarla şifrelenerek
kullanıcının AppData klasöründe saklanır. Düz metin olarak diske yazılmaz.
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
# Yollar
# ----------------------------------------------------------------------------
APP_NAME = "aidesk"


def _base_dir() -> Path:
    """Platforma uygun yapılandırma dizini."""
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
# Şifreleme yardımcıları
# ----------------------------------------------------------------------------
def _machine_passphrase() -> bytes:
    """Makineye bağlı, kabaca sabit bir parola üretir.

    Not: Bu, gelişmiş saldırganlara karşı değil; anahtarların düz metin
    olarak diskte durmamasını sağlamak içindir. Daha güçlü koruma istenirse
    kullanıcıdan bir ana parola alınıp buraya eklenebilir.
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
# Secrets (API anahtarları)
# ----------------------------------------------------------------------------
def load_secrets() -> dict[str, str]:
    if not SECRETS_FILE.exists():
        return {}
    try:
        data = _fernet().decrypt(SECRETS_FILE.read_bytes())
        return json.loads(data.decode("utf-8"))
    except (InvalidToken, ValueError, json.JSONDecodeError):
        # Şifre çözülemezse (ör. makine değişti) boş dön.
        return {}


def save_secrets(secrets: dict[str, str]) -> None:
    blob = _fernet().encrypt(json.dumps(secrets).encode("utf-8"))
    SECRETS_FILE.write_bytes(blob)
    # Yalnızca kullanıcı erişimi (POSIX'te etkili).
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
# Config (hassas olmayan ayarlar)
# ----------------------------------------------------------------------------
@dataclass
class Settings:
    provider: str = "anthropic"            # anthropic | openai | gemini
    model: dict[str, str] = field(default_factory=lambda: {
        "anthropic": "claude-sonnet-5-5",
        "openai": "gpt-4o",
        "gemini": "gemini-3.5-flash",
    })
    hotkey: str = "ctrl+space"             # menüyü aç
    voice_hotkey: str = "ctrl+shift+space" # sesli komut
    stt_mode: str = "auto"                 # auto (bulut varsa bulut) | cloud | local
    mic_name: str = ""                     # boş = otomatik (dahili mikrofon önce)
    whisper_model: str = "base"            # yerel model: tiny|base|small|medium (base: hızlı)
    language: str = "tr"
    require_confirmation: bool = True      # riskli eylemlerde onay iste
    max_tool_iterations: int = 8

    def active_model(self) -> str:
        return self.model.get(self.provider, "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "hotkey": self.hotkey,
            "voice_hotkey": self.voice_hotkey,
            "stt_mode": self.stt_mode,
            "mic_name": self.mic_name,
            "whisper_model": self.whisper_model,
            "language": self.language,
            "require_confirmation": self.require_confirmation,
            "max_tool_iterations": self.max_tool_iterations,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Settings":
        base = cls()
        for k, v in d.items():
            if k == "model" and isinstance(v, dict):
                # Eski kayıtlı modelleri koru, eksik sağlayıcıları varsayılanla doldur.
                # Eski varsayılanlar (emekliye ayrılmış) -> güncel varsayılan
                if v.get("gemini") in ("gemini-1.5-pro", "gemini-2.5-flash"):
                    v = {**v, "gemini": base.model["gemini"]}
                if v.get("anthropic") == "claude-opus-4-8":
                    v = {**v, "anthropic": base.model["anthropic"]}
                base.model = {**base.model, **v}
            elif hasattr(base, k):
                setattr(base, k, v)
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
    """En az bir sağlayıcı için API anahtarı var mı?"""
    secrets = load_secrets()
    return any(k.endswith("_api_key") and v for k, v in secrets.items())
