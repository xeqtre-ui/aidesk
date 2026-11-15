"""Sesli komut — yerel konuşma tanıma (faster-whisper, çevrimdışı).

Düşük seviyeli mikrofonlarda da çalışması için:
- İlk ~0.4 sn ortam gürültüsü ölçülür, konuşma eşiği buna göre ayarlanır.
- Kayıt, mikrofonun kendi örnekleme hızında yapılır ve 16 kHz'e çevrilir.
- Tanımadan önce ses seviyesi normalize edilir (kısık mikrofon yükseltilir).
- Kayıt `stop()` ile elle de bitirilebilir (tıkla-başlat / tıkla-bitir).
"""
from __future__ import annotations

import logging
import os
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
    """16 kHz float32 sesi WAV (int16) baytlarına çevirir."""
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
    """Kullanıcının kendi API anahtarıyla hızlı, yüksek kaliteli yazıya dökme.

    Gemini: ~1 sn. OpenAI: gpt-4o-mini-transcribe. Hata olursa None döner ve
    yerel Whisper'a düşülür.
    """

    # Sadece "lite" modeller: komutların kullandığı flash kotasını yemesin.
    GEMINI_MODELS = ("gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite")
    PROMPT = ("Bu ses kaydındaki konuşmayı olduğu gibi yazıya dök. Sadece söylenen "
              "metni yaz, açıklama ekleme. Konuşma yoksa hiçbir şey yazma.")

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
                    log.warning("Gemini yazıya dökme (%s) başarısız: %s", model, str(e)[:120])
            raise RuntimeError(f"Gemini yazıya dökemedi: {last_error}")
        if self.provider == "openai":
            from openai import OpenAI

            if self._client is None:
                self._client = OpenAI(api_key=self.api_key, timeout=10)
            r = self._client.audio.transcriptions.create(
                model="gpt-4o-mini-transcribe", file=("komut.wav", data), language=self.language
            )
            return (r.text or "").strip()
        raise RuntimeError(f"{self.provider} ses desteklemiyor")


_NOT_A_MIC = ("eşleştirici", "mapper", "stereo mix", "stereo karışımı", "what u hear", "loopback")


def list_microphones() -> list[str]:
    """Varsayılan ses API'sindeki gerçek mikrofonların adları."""
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


_DEAD_MICS: dict[str, float] = {}  # mikrofon adı -> bu zamana kadar sona at
_CLOSERS: list[threading.Thread] = []  # arka planda kapanan akışlar


def _refresh_devices() -> None:
    """Bluetooth cihazlar bağlanıp kopunca liste değişir: PortAudio'yu yenile.
    Hâlâ kapanmakta olan bir akış varsa dokunma (çökme riski)."""
    import sounddevice as sd

    _CLOSERS[:] = [t for t in _CLOSERS if t.is_alive()]
    if _CLOSERS:
        return
    try:
        sd._terminate()
        sd._initialize()
    except Exception:  # noqa: BLE001
        log.debug("Ses cihazı listesi yenilenemedi", exc_info=True)


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

                log.info("Whisper modeli yükleniyor: %s", self.model_size)
                self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
                log.info("Whisper modeli hazır")
        return "Ses modeli hazır."

    # --- Kayıt -------------------------------------------------------------
    def arm(self) -> None:
        """Yeni kayıttan ÖNCE (ana iş parçacığında) çağrılır; erken 'bitir' basışı kaybolmaz."""
        self._stop.clear()

    def stop(self) -> None:
        self._stop.set()

    def _device_candidates(self) -> list[str]:
        """Denenecek mikrofon adları, sırayla:
        1) Ayarlar'da seçilen mikrofon, 2) dahili/kablolu mikrofonlar (sistem
        varsayılanı önce), 3) Bluetooth kulaklıklar. Kulaklık mikrofonu açılınca
        Windows müziği telefon kalitesine düşürdüğü ve bazen hiç ses vermediği
        için varsayılan olarak sona bırakılır. Ses vermeyenler en sona atılır."""
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
                _DEAD_MICS.get(n, 0) > now,          # ölüler en sonda
                n != self.mic_name,                  # seçilen en başta
                is_bt(n),                            # kulaklıklar sonra
                n != default_name,                   # sistem varsayılanı önce
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
                    log.warning("Mikrofon kullanılamadı: %s (%s) — sıradakine geçiliyor", name, e)
                    _DEAD_MICS[name] = time.time() + 600  # 10 dk boyunca sona at
                    last = e
            if last:
                raise NoAudioError("Hiçbir mikrofondan ses gelmiyor. Mikrofon kapalı ya da sessizde olabilir.")
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
        log.info("Mikrofon: %s (%d Hz)", info["name"], sr)
        try:
            while elapsed < max_seconds and not self._stop.is_set():
                try:
                    mono = q.get(timeout=0.1)
                except queue.Empty:
                    waited += 0.1
                    if not frames and waited >= 1.5:
                        raise NoAudioError(info["name"])  # bu mikrofon hiç veri göndermiyor
                    continue
                waited = 0.0
                frames.append(mono)
                elapsed += len(mono) / sr
                level = float(np.sqrt(np.mean(mono ** 2)))
                if on_level:
                    on_level(level)

                if threshold is None:  # ilk 0.4 sn: ortam gürültüsünü ölç
                    noise_levels.append(level)
                    if elapsed >= 0.4:
                        noise = float(np.median(noise_levels))
                        threshold = max(0.0015, noise * 3.0)
                        log.info("Gürültü %.5f, konuşma eşiği %.5f", noise, threshold)
                    continue

                if level > threshold:
                    spoke_time += 0.05
                    silent_for = 0.0
                elif spoke_time >= 0.15:
                    silent_for += 0.05
                    if silent_for >= silence_duration:
                        break
                elif elapsed >= no_speech_timeout:
                    log.info("Konuşma algılanmadı")
                    break
        finally:
            # Ölü Bluetooth mikrofonunu kapatmak ~6 sn sürebiliyor: bekleme, arka planda kapat.
            def _close() -> None:
                try:
                    stream.abort()
                    stream.close()
                except Exception:  # noqa: BLE001
                    pass

            closer = threading.Thread(target=_close, daemon=True)
            _CLOSERS.append(closer)
            closer.start()
        audio = np.concatenate(frames) if frames else np.zeros(0, np.float32)
        return _resample(audio, sr)

    # --- Tanıma ------------------------------------------------------------
    def transcribe(self, audio: np.ndarray) -> str:
        if audio.size < TARGET_SR * 0.3:
            return ""
        peak = float(np.abs(audio).max())
        if peak < 0.0015:  # neredeyse tamamen sessiz
            return ""
        audio = (audio / peak * 0.9).astype(np.float32)  # kısık mikrofonu yükselt
        t0 = time.time()
        if self.cloud is not None:
            try:
                text = self.cloud(audio)
                if text.startswith(("(", "[")) and text.endswith((")", "]")):
                    text = ""  # "(sessizlik)" gibi açıklamalar
                log.info("Tanınan (bulut, %.1f sn): %r", time.time() - t0, text)
                return text
            except Exception as e:  # noqa: BLE001
                log.warning("Bulut ses tanıma başarısız, yerel modele geçiliyor: %s", e)
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
        log.info("Tanınan (yerel, %.1f sn): %r", time.time() - t0, text)
        return text

    def listen(self, on_level: Callable[[float], None] | None = None) -> str:
        return self.transcribe(self.record(on_level=on_level))
