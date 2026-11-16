"""Wake word — starts the assistant with "Hey Jarvis" or a custom phrase.

Two engines:
- Prebuilt model (openWakeWord: hey_jarvis / alexa / hey_mycroft): very light
  (~3 ms / 80 ms of audio), runs entirely on the computer.
- Custom phrase (e.g. "hey asistan"): speech segments are transcribed with local
  Whisper "tiny" and compared against the phrase. A command can also be given in
  a single sentence like "Hey asistan müziği aç"; everything after the phrase
  becomes the command.

The microphone audio is sent nowhere. While Jarvis is speaking/listening,
detection is stopped with `pause()` (so the assistant isn't triggered by its own voice).
"""
from __future__ import annotations

import difflib
import logging
import queue
import re
import sys
import threading
import time
import types
from typing import Callable

import numpy as np

from . import voice

log = logging.getLogger("aidesk.wake")

BUILTIN = {"hey_jarvis": "Hey Jarvis", "alexa": "Alexa", "hey_mycroft": "Hey Mycroft"}
THRESHOLDS = {"low": 0.5, "normal": 0.3, "high": 0.22}   # sensitivity -> threshold
CHUNK = 1280  # 80 ms @ 16 kHz (the chunk openWakeWord expects)


def _import_openwakeword():
    """openwakeword's __init__ imports scipy/sklearn only for model TRAINING.
    Since that isn't needed for detection, we replace that module with an empty
    placeholder (keeps the app ~100 MB smaller)."""
    name = "openwakeword.custom_verifier_model"
    if name not in sys.modules:
        stub = types.ModuleType(name)
        stub.train_custom_verifier = None
        sys.modules[name] = stub
    import openwakeword
    from openwakeword.model import Model

    return openwakeword, Model


def ensure_models(names: list[str]) -> None:
    """Downloads the required model files once if they're missing (a few MB)."""
    import os

    oww, _ = _import_openwakeword()
    folder = os.path.join(os.path.dirname(oww.__file__), "resources", "models")
    have = set(os.listdir(folder)) if os.path.isdir(folder) else set()
    need = [n for n in names if not any(f.startswith(n) and f.endswith(".onnx") for f in have)]
    if need or "melspectrogram.onnx" not in have:
        from openwakeword.utils import download_models

        download_models(model_names=need or names)


def _norm_words(text: str) -> list[str]:
    t = text.replace("I", "ı").replace("İ", "i").lower()
    return re.sub(r"[^\wçğıöşü ]+", " ", t).split()


def match_phrase(text: str, phrase: str, min_ratio: float = 0.8) -> str | None:
    """If the text starts with the phrase (tolerant of small misspellings), returns
    the rest; returns None if it doesn't match."""
    words, target = _norm_words(text), _norm_words(phrase)
    if not words or not target:
        return None
    n = len(target)
    best, best_end = 0.0, 0
    for start in range(0, min(3, len(words))):            # there may be 1-2 filler words at the start
        for end in range(start + max(1, n - 1), min(len(words), start + n + 1) + 1):
            r = difflib.SequenceMatcher(None, " ".join(words[start:end]), " ".join(target)).ratio()
            if r > best:
                best, best_end = r, end
    if best < min_ratio:
        return None
    return " ".join(words[best_end:])


class WakeListener:
    def __init__(self, on_wake: Callable[[str, object], None], word: str = "hey_jarvis",
                 phrase: str = "hey asistan", sensitivity: str = "normal", mic_name: str = "",
                 is_busy: Callable[[], bool] | None = None) -> None:
        self.on_wake = on_wake          # from a background thread: on_wake(remaining_text, audio_or_None)
        self.is_busy = is_busy          # while True (Jarvis speaking/listening) no detection is done
        self.word = word
        self.phrase = phrase
        self.threshold = THRESHOLDS.get(sensitivity, THRESHOLDS["normal"])
        self.mic_name = mic_name
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._thread: threading.Thread | None = None
        self.error: str | None = None
        self.last_score = 0.0

    # --- Control -------------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="wake", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._resume_at = time.time() + 0.8   # let the echo of its own voice fade
        self._paused.clear()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # --- Loop ----------------------------------------------------------------
    def _run(self) -> None:
        try:
            detector = self._make_detector()
            self._listen(detector)
        except Exception as e:  # noqa: BLE001
            self.error = str(e)
            log.exception("Wake word listener stopped")

    def _make_detector(self):
        if self.word in BUILTIN:
            ensure_models([self.word])
            _, Model = _import_openwakeword()
            model = Model(wakeword_models=[self.word], inference_framework="onnx")
            log.info("Wake word: %s (threshold %.2f)", BUILTIN[self.word], self.threshold)
            return _ModelDetector(model, self.word, self.threshold, self)
        log.info("Wake word: custom phrase %r", self.phrase)
        return _PhraseDetector(self.phrase)

    def _listen(self, detector) -> None:
        import sounddevice as sd

        voice._refresh_devices()
        names = voice.SpeechToText(mic_name=self.mic_name)._device_candidates()
        dev = voice._device_index(names[0]) if names else None
        info = sd.query_devices(dev if dev is not None else sd.default.device[0])
        sr = int(info["default_samplerate"]) or 44100
        q: queue.Queue[np.ndarray] = queue.Queue(maxsize=200)

        def _cb(indata, _frames, _time, _status):
            try:
                q.put_nowait(indata[:, 0].copy())
            except queue.Full:
                pass

        self._resume_at = 0.0
        buf = np.zeros(0, np.float32)
        stream = sd.InputStream(device=dev, samplerate=sr, channels=1, dtype="float32",
                                blocksize=int(sr * 0.04), callback=_cb)
        voice.ACTIVE_STREAMS.add(id(self))       # don't let the device list refresh during this
        stream.start()
        log.info("Wake word listening: %s", info["name"])
        try:
            while not self._stop.is_set():
                try:
                    block = q.get(timeout=0.2)
                except queue.Empty:
                    continue
                busy = self._paused.is_set() or bool(self.is_busy and self.is_busy())
                if busy:
                    self._resume_at = time.time() + 0.8   # when it ends, let its own echo fade
                if busy or time.time() < self._resume_at:
                    buf = np.zeros(0, np.float32)
                    detector.reset()
                    continue
                buf = np.concatenate([buf, voice._resample(block, sr)])
                while len(buf) >= CHUNK:
                    chunk, buf = buf[:CHUNK], buf[CHUNK:]
                    hit = detector.feed(chunk)
                    if hit is not None:
                        rest, audio = hit
                        log.info("Woken (remaining: %r)", rest)
                        detector.reset()
                        self._resume_at = time.time() + 2.0   # avoid back-to-back triggers
                        self.on_wake(rest, audio)
        finally:
            voice.ACTIVE_STREAMS.discard(id(self))
            try:
                stream.abort()
                stream.close()
            except Exception:  # noqa: BLE001
                pass


class _ModelDetector:
    def __init__(self, model, name: str, threshold: float, owner: WakeListener) -> None:
        self.model, self.name, self.threshold, self.owner = model, name, threshold, owner
        self.peak = 0.02   # peak level of the last ~2 s (for automatic gain)
        self.hits = 0

    def reset(self) -> None:
        self.model.reset()
        self.hits = 0

    def feed(self, chunk: np.ndarray):
        # Automatic gain: on a quiet mic, boost so that speech peaks at ~0.5
        # (gain limited to 1x–25x so silence noise isn't blown up).
        p = float(np.abs(chunk).max())
        self.peak = max(p, self.peak * 0.97, 0.004)
        gain = float(np.clip(0.5 / self.peak, 1.0, 25.0))
        pcm = (np.clip(chunk * gain, -1, 1) * 32767).astype(np.int16)
        score = float(self.model.predict(pcm)[self.name])
        self.owner.last_score = score
        # Avoid waking on momentary noise spikes: two consecutive measurements must
        # pass the threshold (or a single measurement must be very strong). A real
        # "Hey Jarvis" lasts ~0.5 s.
        self.hits = self.hits + 1 if score >= self.threshold else 0
        return ("", None) if self.hits >= 2 or score >= self.threshold + 0.35 else None


class _PhraseDetector:
    """Simple energy-based speech detection + phrase matching with local Whisper tiny."""

    def __init__(self, phrase: str) -> None:
        self.phrase = phrase
        self.stt = voice.SpeechToText("tiny", "tr")
        self.stt.preload()
        self.reset()

    def reset(self) -> None:
        self.frames: list[np.ndarray] = []
        self.noise = 0.004
        self.speech = 0.0
        self.silence = 0.0

    def feed(self, chunk: np.ndarray):
        level = float(np.sqrt(np.mean(chunk ** 2)))
        loud = level > max(0.0025, self.noise * 3.0)
        dt = len(chunk) / voice.TARGET_SR
        if not loud and not self.frames:
            self.noise = self.noise * 0.95 + level * 0.05      # track ambient noise
            return None
        self.frames.append(chunk)
        if loud:
            self.speech += dt
            self.silence = 0.0
        else:
            self.silence += dt
        total = len(self.frames) * dt
        if self.silence < 0.6 and total < 6.0:
            return None
        audio = np.concatenate(self.frames)
        spoke = self.speech
        self.reset()
        if spoke < 0.25:                                        # too short: noise
            return None
        text = self.stt.transcribe(audio)
        rest = match_phrase(text, self.phrase)
        # The small model only decides "did the phrase occur"; the command itself
        # is re-transcribed in the controller with the real (more accurate) recognition.
        return (rest, audio) if rest is not None else None
