"""Whistle wrapper: speech -> text, English only, with keyword biasing.

Verified against cactus-needle 3.2.8:
    needle.transcribe(audio, language=None, keywords=None,
                      word_timestamps=False, weights=None) -> dict
    returns {"text", "language", "ttft_ms", "decode_tps"}
`audio` is a WAV path or 16 kHz mono float samples in [-1, 1].
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import assistant  # noqa: F401  (sets telemetry/offline env before needle import)


@dataclass
class Transcript:
    text: str
    latency_ms: float      # wall clock for the transcribe call
    ttft_ms: float | None  # engine: time to first token
    decode_tps: float | None
    audio_seconds: float


class SpeechToText:
    def __init__(self, language: str = "en", keywords: list[str] | None = None):
        import needle

        self._needle = needle
        self.language = language
        self.keywords = keywords or None

    def transcribe(self, audio) -> Transcript:
        if isinstance(audio, str):
            audio_seconds = _wav_seconds(audio)
        else:
            audio_seconds = len(audio) / 16_000
            if len(audio) == 0:
                return Transcript("", 0.0, None, None, 0.0)
        t0 = time.perf_counter()
        result = self._needle.transcribe(audio, language=self.language,
                                         keywords=self.keywords)
        latency = (time.perf_counter() - t0) * 1000
        return Transcript(
            text=(result.get("text") or "").strip(),
            latency_ms=latency,
            ttft_ms=result.get("ttft_ms"),
            decode_tps=result.get("decode_tps"),
            audio_seconds=audio_seconds,
        )


def _wav_seconds(path: str) -> float:
    import wave
    with wave.open(path, "rb") as w:
        return w.getnframes() / float(w.getframerate())
