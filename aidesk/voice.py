"""Voice command — local speech recognition (faster-whisper, offline).

To also work with low-grade microphones:
- The first ~0.4 s measures ambient noise and sets the speech threshold accordingly.
- Recording is done at the microphone's own sample rate and converted to 16 kHz.
- The level is normalized before recognition (a quiet mic is boosted).
- Recording can also be ended by hand with `stop()` (click-to-start / click-to-stop).
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Callable

import numpy as np

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
log = logging.getLogger("aidesk.voice")
TARGET_SR = 16000


def _resample(audio: np.ndarray, sr: int) -> np.ndarray:
    if sr == TARGET_SR or audio.size == 0:
        return audio.astype(np.float32)
    n = int(len(audio) * TARGET_SR / sr)
    x_old = np.linspace(0.0, 1.0, num=len(audio), endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=n, endpoint=False)
    return np.interp(x_new, x_old, audio).astype(np.float32)


def _wav_bytes(audio: np.ndarray) -> bytes:
    """Converts 16 kHz float32 audio to WAV (int16) bytes."""
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TARGET_SR)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


class CloudTranscriber:
    """Fast, high-quality transcription with the user's own API key.

    Gemini: ~1 s. OpenAI: gpt-4o-mini-transcribe. On error it returns None and
    falls back to local Whisper.
    """

    # Only "lite" models: don't eat into the flash quota the commands use.
    GEMINI_MODELS = ("gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite")
    PROMPT = ("Transcribe the speech in this recording exactly as spoken. Write only the "
              "spoken text, add no explanation. If there is no speech, write nothing.")

    def __init__(self, provider: str, api_key: str, language: str) -> None:
        self.provider = provider
        self.api_key = api_key
        self.language = language
        self._client = None

    def __call__(self, audio: np.ndarray) -> str:
        data = _wav_bytes(audio)
        if self.provider == "gemini":
            from google import genai
            from google.genai import types

            if self._client is None:
                self._client = genai.Client(
                    api_key=self.api_key,
                    http_options=types.HttpOptions(
                        timeout=10_000, retry_options=types.HttpRetryOptions(attempts=1)
                    ),
                )
            from . import apierrors

            last_error: Exception | None = None
            for model in self.GEMINI_MODELS:
                if apierrors.is_cooling(model):
                    continue
                try:
                    r = self._client.models.generate_content(
                        model=model,
                        contents=[types.Part.from_bytes(data=data, mime_type="audio/wav"), self.PROMPT],
                        config=types.GenerateContentConfig(temperature=0),
                    )
                    return (r.text or "").strip()
                except Exception as e:  # noqa: BLE001
                    last_error = e
                    code = apierrors.status_code(e)
                    apierrors.cool(model, apierrors.retry_delay(e) if code == 429 else 300)
                    log.warning("Gemini transcription (%s) failed: %s", model, str(e)[:120])
            raise RuntimeError(f"Gemini could not transcribe: {last_error}")
        if self.provider == "openai":
            from openai import OpenAI

            if self._client is None:
                self._client = OpenAI(api_key=self.api_key, timeout=10)
            r = self._client.audio.transcriptions.create(
                model="gpt-4o-mini-transcribe", file=("command.wav", data), language=self.language
            )
            return (r.text or "").strip()
        raise RuntimeError(f"{self.provider} does not support audio")


_NOT_A_MIC = ("eşleştirici", "mapper", "stereo mix", "stereo karışımı", "what u hear", "loopback")


def list_microphones() -> list[str]:
    """Names of the real microphones in the default audio API."""
    import sounddevice as sd

    host = sd.default.hostapi
    names: list[str] = []
    for d in sd.query_devices():
        if d["max_input_channels"] > 0 and d["hostapi"] == host:
            name = d["name"]
            if not any(x in name.lower() for x in _NOT_A_MIC) and name not in names:
                names.append(name)
    return names


class NoAudioError(RuntimeError):
    pass


_DEAD_MICS: dict[str, float] = {}  # mic name -> deprioritize until this time
_CLOSERS: list[threading.Thread] = []  # streams closing in the background
ACTIVE_STREAMS: set[int] = set()       # continuously open streams (e.g. wake word)


def _refresh_devices() -> None:
    """When Bluetooth devices connect/disconnect the list changes: refresh PortAudio.
    If a stream is still closing, don't touch it (crash risk)."""
    import sounddevice as sd

    _CLOSERS[:] = [t for t in _CLOSERS if t.is_alive()]
    if _CLOSERS or ACTIVE_STREAMS:   # refreshing while a stream is open breaks it
        return
    try:
        sd._terminate()
        sd._initialize()
    except Exception:  # noqa: BLE001
        log.debug("Could not refresh audio device list", exc_info=True)


def _device_index(name: str) -> int | None:
    import sounddevice as sd

    host = sd.default.hostapi
    for i, d in enumerate(sd.query_devices()):
        if d["name"] == name and d["max_input_channels"] > 0 and d["hostapi"] == host:
            return i
    return None


class SpeechToText:
    def __init__(self, model_size: str = "base", language: str = "tr",
                 cloud: CloudTranscriber | None = None, mic_name: str = "") -> None:
        self.model_size = model_size
        self.language = language
        self.cloud = cloud
        self.mic_name = mic_name
        self.active_mic = ""
        self._model = None
        self._load_lock = threading.Lock()
        self._stop = threading.Event()
        self.recording = False

    # --- Model -------------------------------------------------------------
    @property
    def ready(self) -> bool:
        return self._model is not None

    def preload(self) -> str:
        with self._load_lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                log.info("Loading Whisper model: %s", self.model_size)
                self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
                log.info("Whisper model ready")
        return "Voice model ready."

    # --- Recording ---------------------------------------------------------
    def arm(self) -> None:
        """Called BEFORE a new recording (on the main thread); an early 'finish' press isn't lost."""
        self._stop.clear()

    def stop(self) -> None:
        self._stop.set()

    def _device_candidates(self) -> list[str]:
        """Microphone names to try, in order:
        1) the mic selected in Settings, 2) built-in/wired mics (system default
        first), 3) Bluetooth headsets. When a headset mic is opened Windows drops
        the music to phone quality and sometimes gives no audio at all, so it is
        left for last by default. Mics that give no audio are pushed to the very end."""
        import sounddevice as sd

        _refresh_devices()
        names = list_microphones()
        try:
            default_name = sd.query_devices(kind="input")["name"]
        except Exception:  # noqa: BLE001
            default_name = ""
        bt = ("airpods", "kulaklık", "headset", "hands-free", "buds", "bluetooth", "earbuds")
        is_bt = lambda n: any(b in n.lower() for b in bt)  # noqa: E731
        now = time.time()
        order = sorted(
            names,
            key=lambda n: (
                _DEAD_MICS.get(n, 0) > now,          # dead ones last
                n != self.mic_name,                  # the selected one first
                is_bt(n),                            # headsets later
                n != default_name,                   # system default first
            ),
        )
        return order

    def record(
        self,
        max_seconds: float = 20.0,
        silence_duration: float = 0.9,
        no_speech_timeout: float = 8.0,
        on_level: Callable[[float], None] | None = None,
    ) -> np.ndarray:
        self.recording = True
        try:
            import sounddevice as sd

            last: Exception | None = None
            for name in self._device_candidates():
                if self._stop.is_set():
                    break
                dev = _device_index(name)
                if dev is None:
                    continue
                self.active_mic = name
                try:
                    return self._record_from(dev, max_seconds, silence_duration, no_speech_timeout, on_level)
                except (NoAudioError, sd.PortAudioError) as e:
                    log.warning("Microphone unusable: %s (%s) — moving to the next", name, e)
                    _DEAD_MICS[name] = time.time() + 600  # deprioritize for 10 min
                    last = e
            if last:
                raise NoAudioError("No audio from any microphone. The mic may be off or muted.")
            return np.zeros(0, np.float32)
        finally:
            self.recording = False

    def _record_from(self, device, max_seconds, silence_duration, no_speech_timeout, on_level) -> np.ndarray:
        import queue

        import sounddevice as sd

        info = sd.query_devices(device)
        sr = int(info["default_samplerate"]) or 44100
        block = int(sr * 0.05)  # 50 ms
        q: queue.Queue[np.ndarray] = queue.Queue()

        def _cb(indata, _frames, _time, _status):
            q.put(indata[:, 0].copy())

        frames: list[np.ndarray] = []
        noise_levels: list[float] = []
        threshold = None
        spoke_time = silent_for = elapsed = 0.0
        waited = 0.0
        stream = sd.InputStream(device=device, samplerate=sr, channels=1, dtype="float32",
                                blocksize=block, callback=_cb)
        stream.start()
        log.info("Microphone: %s (%d Hz)", info["name"], sr)
        try:
            while elapsed < max_seconds and not self._stop.is_set():
                try:
                    mono = q.get(timeout=0.1)
                except queue.Empty:
                    waited += 0.1
                    if not frames and waited >= 1.5:
                        raise NoAudioError(info["name"])  # this mic sends no data at all
                    continue
                waited = 0.0
                frames.append(mono)
                elapsed += len(mono) / sr
                level = float(np.sqrt(np.mean(mono ** 2)))
                if on_level:
                    on_level(level)

                if threshold is None:  # first 0.4 s: measure ambient noise
                    noise_levels.append(level)
                    if elapsed >= 0.4:
                        noise = float(np.median(noise_levels))
                        threshold = max(0.0015, noise * 3.0)
                        log.info("Noise %.5f, speech threshold %.5f", noise, threshold)
                    continue

                if level > threshold:
                    spoke_time += 0.05
                    silent_for = 0.0
                elif spoke_time >= 0.15:
                    silent_for += 0.05
                    if silent_for >= silence_duration:
                        break
                elif elapsed >= no_speech_timeout:
                    log.info("No speech detected")
                    break
        finally:
            # Closing a dead Bluetooth mic can take ~6 s: don't wait, close it in the background.
            def _close() -> None:
                try:
                    stream.abort()
                    stream.close()
                except Exception:  # noqa: BLE001
                    pass

            closer = threading.Thread(target=_close, daemon=True)
            _CLOSERS.append(closer)
            closer.start()
        if spoke_time < 0.25:          # no real speech: noise/silence
            return np.zeros(0, np.float32)
        audio = np.concatenate(frames) if frames else np.zeros(0, np.float32)
        return _resample(audio, sr)

    # --- Recognition -------------------------------------------------------
    @staticmethod
    def is_junk(text: str) -> bool:
        """Text that speech recognition invents on silence/noise ("00:00", "Bu",
        "Altyazı M.K." etc.). The phrase list is Turkish because it matches
        Turkish ASR hallucinations; kept as-is."""
        t = text.strip().lower()
        letters = re.sub(r"[^a-zçğıöşü]", "", t)
        if len(letters) < 3:
            return True
        junk = ("altyazı", "abone ol", "izlediğiniz için", "teşekkürler izlediğiniz",
                "subtitles by", "thank you for watching", "müzik çalıyor")
        return any(j in t for j in junk) and len(t) < 40

    def transcribe(self, audio: np.ndarray) -> str:
        if audio.size < TARGET_SR * 0.3:
            return ""
        peak = float(np.abs(audio).max())
        if peak < 0.0015:  # almost completely silent
            return ""
        audio = (audio / peak * 0.9).astype(np.float32)  # boost a quiet mic
        t0 = time.time()
        if self.cloud is not None:
            try:
                text = self.cloud(audio)
                if (text.startswith(("(", "[")) and text.endswith((")", "]"))) or self.is_junk(text):
                    log.info("Skipped meaningless recognition: %r", text)
                    text = ""  # inventions like "(silence)", "00:00"
                log.info("Recognized (cloud, %.1f s): %r", time.time() - t0, text)
                return text
            except Exception as e:  # noqa: BLE001
                log.warning("Cloud speech recognition failed, falling back to local model: %s", e)
        self.preload()
        segments, _ = self._model.transcribe(
            audio,
            language=self.language,
            beam_size=1,
            without_timestamps=True,
            condition_on_previous_text=False,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        log.info("Recognized (local, %.1f s): %r", time.time() - t0, text)
        return "" if self.is_junk(text) else text

    def listen(self, on_level: Callable[[float], None] | None = None) -> str:
        return self.transcribe(self.record(on_level=on_level))
