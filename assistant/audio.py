"""Push-to-talk microphone capture, 16 kHz mono float32, held in memory only.

Spec 8.4: audio is never written to disk. Spec 11: capture at 16 kHz natively.
Some Windows input devices refuse 16 kHz; only then do we open at the device's
native rate and resample with soxr (the same fallback cactus-needle uses).
"""
from __future__ import annotations

import threading

import numpy as np

SAMPLE_RATE = 16_000


class Recorder:
    def __init__(self, max_seconds: float = 30.0):
        self.max_seconds = max_seconds
        self._chunks: list[np.ndarray] = []
        self._stream = None
        self._rate = SAMPLE_RATE
        self._lock = threading.Lock()

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def _callback(self, data, frames, time_info, status):  # sounddevice callback
        with self._lock:
            self._chunks.append(data[:, 0].copy())

    def start(self) -> None:
        import sounddevice as sd

        if self._stream is not None:
            return
        self._chunks = []
        try:
            self._rate = SAMPLE_RATE
            stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                    dtype="float32", callback=self._callback)
        except sd.PortAudioError:
            self._rate = int(sd.query_devices(kind="input")["default_samplerate"])
            stream = sd.InputStream(samplerate=self._rate, channels=1,
                                    dtype="float32", callback=self._callback)
        stream.start()
        self._stream = stream

    def stop(self) -> np.ndarray:
        """Stop capture; return 16 kHz mono float32 samples in [-1, 1]."""
        stream, self._stream = self._stream, None
        if stream is None:
            return np.zeros(0, dtype=np.float32)
        stream.stop()
        stream.close()
        with self._lock:
            audio = (np.concatenate(self._chunks) if self._chunks
                     else np.zeros(0, dtype=np.float32))
            self._chunks = []
        if self._rate != SAMPLE_RATE:
            import soxr
            audio = soxr.resample(audio, self._rate, SAMPLE_RATE, quality="HQ")
        cap = int(self.max_seconds * SAMPLE_RATE)
        return np.clip(audio[:cap], -1.0, 1.0).astype(np.float32)
