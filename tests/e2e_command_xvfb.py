"""Phase 2 gate by voice on a virtual X display.

    xvfb-run -a python tests/e2e_command_xvfb.py

Real: pynput hotkey (Ctrl+Alt+Space held via xdotool), Whistle, Needle 3, the
gate, AppLauncher's subprocess launch, the JSONL log. Simulated: the microphone
(fixture WAVs) and Notepad (a stub `notepad.exe` on PATH that writes a marker).
"""
from __future__ import annotations

import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import wave
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIX = ROOT / "tests" / "fixtures"


def read_wav(path):
    import numpy as np
    with wave.open(str(path), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), "<i2").astype("float32") / 32768


class Tee(io.TextIOBase):
    def __init__(self):
        self.buf = []
    def write(self, s):
        sys.__stdout__.write(s); self.buf.append(s); return len(s)
    def text(self):
        return "".join(self.buf)


def main():
    confirm_mode = "--confirm" in sys.argv
    tmp = Path(tempfile.mkdtemp())
    marker = tmp / "notepad_launched"
    stub = tmp / "notepad.exe"
    stub.write_text(f"#!/bin/sh\ntouch {marker}\n")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    os.environ["PATH"] = f"{tmp}{os.pathsep}{os.environ['PATH']}"

    import assistant.audio
    import run
    from assistant import config as cfgmod

    current = {"samples": None}

    class WavRecorder:
        def __init__(self, *_):
            self.recording = False
        def start(self):
            self.recording = True
        def stop(self):
            self.recording = False
            return current["samples"]
    assistant.audio.Recorder = WavRecorder

    log_path = tmp / "log.jsonl"
    real_load = cfgmod.load
    def load(path=None):
        cfg = real_load(path)
        cfg.setdefault("log", {})["path"] = str(log_path)
        if confirm_mode:  # force every call into the confirm band
            cfg["intent"]["act_threshold"] = 0.99
            cfg["intent"]["confirm_threshold"] = 0.05
            cfg["intent"]["confirm_timeout_s"] = 2
        return cfg
    cfgmod.load = load

    out = Tee()
    def serve():
        with redirect_stdout(out):
            run.run_hotkeys(no_paste=True)
    threading.Thread(target=serve, daemon=True).start()
    while "Ready." not in out.text():
        time.sleep(0.2)
    time.sleep(1)

    def say(fixture, answer=None):
        current["samples"] = read_wav(FIX / f"{fixture}.wav")
        n = len(out.text())
        subprocess.run(["xdotool", "keydown", "ctrl+alt+space"], check=True)
        time.sleep(len(current["samples"]) / 16000)
        subprocess.run(["xdotool", "keyup", "space", "alt", "ctrl"], check=True)
        if answer:
            while "Confirm?" not in out.text()[n:]:
                time.sleep(0.05)
            time.sleep(0.3)
            if answer == "hotkey":
                subprocess.run(["xdotool", "key", "ctrl+alt+space"], check=True)
            elif answer == "esc":
                subprocess.run(["xdotool", "key", "Escape"], check=True)
        deadline = time.time() + 30
        while "release→done" not in out.text()[n:] and time.time() < deadline:
            time.sleep(0.05)
        time.sleep(0.3)

    if confirm_mode:
        say("command_open_notepad", "hotkey"); time.sleep(0.5)
        launched = marker.exists()
        marker.unlink(missing_ok=True)
        say("command_open_notepad", "esc"); time.sleep(0.5)
        launched_after_esc = marker.exists()
        say("command_open_notepad", "timeout"); time.sleep(0.5)
        launched_after_timeout = marker.exists()
        rows = [json.loads(l) for l in log_path.read_text().splitlines()]
        checks = {
            "hotkey again -> confirmed, notepad launched":
                rows[0]["route"] == "confirm" and rows[0]["confirmed"] is True and launched,
            "Esc -> cancelled, nothing launched":
                rows[1]["confirmed"] is False and not launched_after_esc,
            "timeout -> cancelled, nothing launched":
                rows[2]["confirmed"] is False and not launched_after_timeout,
            "confirm answers did not start a new recording": len(rows) == 3,
        }
        print("\n==== confirm band ====")
        for k, v in checks.items():
            print(f"  {'PASS' if v else 'FAIL'}  {k}")
        return 0 if all(checks.values()) else 1

    results = {}
    say("command_what_time")
    say("command_open_notepad"); time.sleep(0.5)
    results["notepad_launched"] = marker.exists()
    say("command_nonsense")

    rows = [json.loads(l) for l in log_path.read_text().splitlines()]
    print("\n==== log.jsonl ====")
    for r in rows:
        print(f"  {r['query']!r:36} answers={json.dumps(r['answers'])} conf={r['confidence']}"
              f" route={r['route']} executed={r['executed']} results={r['results']}")
    checks = {
        "what time is it -> get_time executed":
            rows[0]["route"] == "act" and rows[0]["answers"][0]["name"] == "get_time" and rows[0]["executed"],
        "open notepad -> open_app(notepad) executed":
            rows[1]["route"] == "act" and rows[1]["answers"] == [{"name": "open_app", "arguments": {"name": "notepad"}}],
        "notepad process actually launched": results["notepad_launched"],
        "nonsense -> empty function_calls, nothing executed":
            rows[2]["answers"] == [] and not rows[2]["executed"],
        "3 utterances logged": len(rows) == 3,
    }
    print("\n==== Phase 2 gate ====")
    for k, v in checks.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
