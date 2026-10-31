"""End-to-end Phase 1 check on a virtual X display (no mic, no Windows needed).

    xvfb-run -a python tests/e2e_xvfb.py tests/fixtures/dictation_01.wav
    xvfb-run -a python tests/e2e_xvfb.py --stub-stt tests/fixtures/dictation_01.wav

What is real: global hotkey listener (pynput), push-to-talk timing, Whistle
transcription, clipboard save/set/restore (pyperclip+xclip), synthetic Ctrl+V
into a real Tk text box, end-to-end latency.
What is simulated: the microphone - the WAV's samples stand in for capture.
--stub-stt replaces Whistle with the fixture's .txt (plumbing check only).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TARGET_APP = r'''
import sys, tkinter as tk
out = sys.argv[1]
root = tk.Tk(); root.title("target"); root.geometry("600x200+0+0")
t = tk.Text(root); t.pack(fill="both", expand=True); t.focus_force()
def dump():
    open(out, "w").write(t.get("1.0", "end-1c")); root.after(100, dump)
root.after(300, lambda: (root.focus_force(), t.focus_set())); dump(); root.mainloop()
'''


def read_wav(path):
    import numpy as np
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1, "need 16 kHz mono"
        return np.frombuffer(w.readframes(w.getnframes()), "<i2").astype("float32") / 32768


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--stub-stt", action="store_true")
    a = ap.parse_args()
    wav = Path(a.wav)
    samples = read_wav(wav)

    import assistant.audio
    import assistant.stt
    import run

    class WavRecorder:  # stands in for the microphone
        def __init__(self, *_):
            self.recording = False
        def start(self):
            self.recording = True
        def stop(self):
            self.recording = False
            return samples
    assistant.audio.Recorder = WavRecorder

    if a.stub_stt:
        expected = wav.with_suffix(".txt").read_text().strip()
        class StubSTT:
            def __init__(self, *_a, **_k): pass
            def transcribe(self, audio):
                return assistant.stt.Transcript(expected, 0.0, None, None, len(audio) / 16000)
        assistant.stt.SpeechToText = StubSTT

    out = Path(tempfile.mkdtemp()) / "target.txt"
    app = subprocess.Popen([sys.executable, "-c", TARGET_APP, str(out)])
    time.sleep(1.5)

    import pyperclip
    pyperclip.copy("ORIGINAL-CLIPBOARD")

    threading.Thread(target=run.run_hotkeys, args=(False,), daemon=True).start()
    time.sleep(8 if not a.stub_stt else 2)  # warm-up + listener start

    subprocess.run(["xdotool", "search", "--name", "target", "windowactivate", "--sync"], check=False)
    subprocess.run(["xdotool", "keydown", "ctrl+alt+d"], check=True)
    time.sleep(len(samples) / 16000)  # "speak" for the clip's duration
    subprocess.run(["xdotool", "keyup", "d", "alt", "ctrl"], check=True)

    deadline, text = time.time() + 30, ""
    while time.time() < deadline:
        text = out.read_text() if out.exists() else ""
        if text:
            break
        time.sleep(0.05)
    time.sleep(0.6)
    clip = pyperclip.paste()
    app.terminate()
    print(f"\nTARGET TEXT BOX : {text!r}")
    print(f"CLIPBOARD AFTER : {clip!r}")
    ok = bool(text) and clip == "ORIGINAL-CLIPBOARD"
    print("RESULT          :", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
