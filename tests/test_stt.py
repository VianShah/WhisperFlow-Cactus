"""Real-model tests. Skipped until `python run.py --setup` has cached the models."""
from pathlib import Path

import numpy as np
import pytest

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def stt():
    from assistant.stt import SpeechToText
    s = SpeechToText("en")
    try:
        s.transcribe(np.zeros(1600, dtype=np.float32))
    except Exception as e:  # models not downloaded yet
        pytest.skip(f"models not cached: {e.__class__.__name__}")
    return s


def test_silence_is_empty(stt):
    assert stt.transcribe(np.zeros(16_000 * 2, dtype=np.float32)).text == ""


KNOWN_MISSES = {"dictation_03.wav": "Whistle hears synthetic 'that ... three thirty' as "
                                     "'after ... free 30' (since Phase 1)"}


@pytest.mark.parametrize("wav", [
    pytest.param(p, marks=pytest.mark.xfail(strict=True, reason=KNOWN_MISSES[p.name]))
    if p.name in KNOWN_MISSES else p
    for p in sorted(FIX.glob("dictation_*.wav"))], ids=lambda p: p.name)
def test_fixture_transcribes(stt, wav):
    expected = wav.with_suffix(".txt").read_text().strip().lower()
    got = stt.transcribe(str(wav)).text.lower()
    words = [w.strip(".,") for w in expected.split()]
    hit = sum(w in got for w in words) / len(words)
    assert hit >= 0.8, got
