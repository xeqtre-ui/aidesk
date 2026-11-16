"""Voice response (text to speech).

Engines:
- "windows": Windows' own voice (e.g. Microsoft Tolga, Turkish). Offline,
  instant, free. Default.
- "openai" : OpenAI gpt-4o-mini-tts (more natural; needs an OpenAI key).

During playback the level of each audio block is reported via `on_level`; the
Jarvis orb grows and shrinks with it. `stop()` cuts off speech instantly.
"""
from __future__ import annotations

import asyncio
import io
import logging
import re
import threading
import time
import wave
from typing import Callable

import numpy as np

log = logging.getLogger("aidesk.tts")

_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]+")


def clean_for_speech(text: str) -> str:
    """Strips marks unsuitable for speech (markdown, emoji, URL)."""
    # "bağlantı" (Turkish for "link") is kept: it is spoken aloud by the Turkish voice.
    t = re.sub(r"https?://\S+", "bağlantı", text)
    t = re.sub(r"[*_`#>|~]+", "", t)
    t = _EMOJI.sub("", t)
    t = t.replace("—", ", ").replace("–", ", ")
    return re.sub(r"\s+", " ", t).strip()


def _decode_wav(data: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(data)) as w:
        sr, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError(f"Unsupported sample width: {width}")
    audio = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        audio = audio.reshape(-1, ch).mean(axis=1)
    return audio, sr


def windows_voices() -> list[str]:
    try:
        from winsdk.windows.media.speechsynthesis import SpeechSynthesizer

        return [f"{v.display_name} ({v.language})" for v in SpeechSynthesizer.all_voices]
    except Exception:  # noqa: BLE001
        return []


class Speaker:
    def __init__(self, engine: str = "windows", voice: str = "", language: str = "tr",
                 openai_key: str | None = None, rate: float = 1.1) -> None:
        self.engine = engine
        self.voice = voice          # "Microsoft Tolga (tr-TR)" or an OpenAI voice name
        self.language = language
        self.openai_key = openai_key
        self.rate = rate
        self._stop = threading.Event()
        self.speaking = False

    # --- Synthesis ---------------------------------------------------------
    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        from . import apierrors

        if self.engine == "openai" and self.openai_key and not apierrors.is_cooling("openai-tts"):
            try:
                return self._synth_openai(text)
            except Exception as e:  # noqa: BLE001
                log.warning("OpenAI voice failed, switching to the Windows voice: %s", str(e)[:120])
                apierrors.cool("openai-tts", 3600)   # if no credit/quota, don't try for an hour
        return asyncio.run(self._synth_windows(text))

    async def _synth_windows(self, text: str) -> tuple[np.ndarray, int]:
        from winsdk.windows.media.speechsynthesis import SpeechSynthesizer
        from winsdk.windows.storage.streams import DataReader

        synth = SpeechSynthesizer()
        voices = list(SpeechSynthesizer.all_voices)
        chosen = next((v for v in voices if self.voice and self.voice.startswith(v.display_name)), None)
        if chosen is None:  # first voice matching the language (e.g. tr-TR)
            chosen = next((v for v in voices if v.language.lower().startswith(self.language)), None)
        if chosen is not None:
            synth.voice = chosen
        synth.options.speaking_rate = self.rate
        stream = await synth.synthesize_text_to_stream_async(text)
        size = int(stream.size)
        reader = DataReader(stream.get_input_stream_at(0))
        await reader.load_async(size)
        buf = bytearray(size)
        reader.read_bytes(buf)
        return _decode_wav(bytes(buf))

    def _synth_openai(self, text: str) -> tuple[np.ndarray, int]:
        from openai import OpenAI

        client = OpenAI(api_key=self.openai_key, timeout=20)
        resp = client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice=self.voice or "onyx",
            input=text,
            response_format="wav",
            instructions="Speak like a calm, confident, helpful AI assistant.",
        )
        return _decode_wav(resp.read())

    # --- Playback ----------------------------------------------------------
    def stop(self) -> None:
        self._stop.set()

    def speak(self, text: str, on_level: Callable[[float], None] | None = None) -> bool:
        """Speaks the text; waits until it finishes or stop() is called.
        Returns True if it finished without being interrupted."""
        import sounddevice as sd

        text = clean_for_speech(text)
        if not text:
            return True
        self._stop.clear()
        audio, sr = self.synthesize(text)
        if self._stop.is_set():
            return False
        # The level envelope for the orb is computed IN ADVANCE (30 ms windows).
        # This way the audio callback only copies data; audio doesn't stutter even
        # while the CPU is busy (drawing the orb etc.).
        win = max(1, int(sr * 0.03))
        n = len(audio) // win + 1
        env = np.sqrt((np.pad(audio, (0, n * win - len(audio))).reshape(n, win) ** 2).mean(axis=1))
        # Short silence at the end: so the last syllable isn't clipped / doesn't crackle
        audio = np.concatenate([audio, np.zeros(int(sr * 0.12), np.float32)])
        pos = 0
        underruns = 0
        done = threading.Event()

        def _cb(outdata, frames, _time, status):
            nonlocal pos, underruns
            if status.output_underflow:
                underruns += 1
            chunk = audio[pos:pos + frames]
            pos += frames
            outdata[: len(chunk), 0] = chunk
            outdata[len(chunk):, 0] = 0
            if len(chunk) < frames:
                raise sd.CallbackStop

        self.speaking = True
        try:
            # Large buffer + high latency: so there's no stutter (buffer underrun)
            with sd.OutputStream(samplerate=sr, channels=1, dtype="float32", blocksize=2048,
                                 latency="high", callback=_cb, finished_callback=done.set) as stream:
                latency = float(stream.latency or 0.0)
                t0 = time.perf_counter()
                while not done.wait(0.03):
                    if self._stop.is_set():
                        stream.abort()
                        break
                    if on_level:
                        i = int((time.perf_counter() - t0 - latency) / 0.03)
                        on_level(float(env[i]) if 0 <= i < len(env) else 0.0)
        finally:
            self.speaking = False
            if on_level:
                on_level(0.0)
        if underruns:
            log.warning("Buffer underran %d times during speech", underruns)
        return not self._stop.is_set()
