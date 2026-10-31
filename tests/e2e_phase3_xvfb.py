"""Phase 3: all four action families by voice on a virtual X display.

    xvfb-run -a python tests/e2e_phase3_xvfb.py

Real: pynput hotkeys, Whistle, Needle 3 (12 tools), the gate + hotkey
confirmation, AppLauncher subprocess launch, SQLite reminders + the in-process
poller firing a reminder, os.walk file search, open-by-result-number, JSONL log.
Simulated: the mic (Piper-voiced fixture WAVs), Notepad and the file opener
(stubs on PATH that record they ran). Windows-only actions (window control,
volume) are checked to fail cleanly, not faked.

Uses [intent.confirm_floor] set_reminder/find_file = 0.1 so those calls reach the
confirm band (with the spec defaults they are refused at their ~0.2-0.3 scores).
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


def stub(dirpath: Path, name: str, marker: Path):
    p = dirpath / name
    p.write_text(f'#!/bin/sh\necho "$@" >> {marker}\n')
    p.chmod(p.stat().st_mode | stat.S_IEXEC)


def main():
    tmp = Path(tempfile.mkdtemp())
    bindir = tmp / "bin"; bindir.mkdir()
    notepad_marker, open_marker = tmp / "notepad_ran", tmp / "opened"
    stub(bindir, "notepad.exe", notepad_marker)
    stub(bindir, "xdg-open", open_marker)
    os.environ["PATH"] = f"{bindir}{os.pathsep}{os.environ['PATH']}"
    docs = tmp / "Documents"; docs.mkdir()
    (docs / "Budget spreadsheet 2026.xlsx").write_text("x")
    (docs / "holiday photos.zip").write_text("x")

    import assistant.audio
    import run
    from assistant import config as cfgmod

    current = {"samples": None}

    class WavRecorder:
        def __init__(self, *_): self.recording = False
        def start(self): self.recording = True
        def stop(self):
            self.recording = False
            return current["samples"]
    assistant.audio.Recorder = WavRecorder

    log_path = tmp / "log.jsonl"
    real_load = cfgmod.load
    def load(path=None):
        cfg = real_load(path)
        cfg["log"]["path"] = str(log_path)
        cfg["reminders"]["db"] = str(tmp / "reminders.db")
        cfg["files"]["fallback_roots"] = [str(docs)]
        cfg["files"]["everything_cli"] = ""
        cfg["intent"]["confirm_floor"] = {"set_reminder": 0.1, "find_file": 0.1}
        return cfg
    cfgmod.load = load

    out = Tee()
    def serve():
        with redirect_stdout(out):
            run.run_hotkeys(no_paste=True, no_tray=True)
    threading.Thread(target=serve, daemon=True).start()
    while "Ready." not in out.text():
        time.sleep(0.2)
    time.sleep(1)

    def say(fixture):
        current["samples"] = read_wav(FIX / f"{fixture}.wav")
        n = len(out.text())
        subprocess.run(["xdotool", "keydown", "ctrl+alt+space"], check=True)
        time.sleep(len(current["samples"]) / 16000)
        subprocess.run(["xdotool", "keyup", "space", "alt", "ctrl"], check=True)
        deadline = time.time() + 30
        confirmed = False
        while time.time() < deadline:
            seg = out.text()[n:]
            if "Confirm?" in seg and not confirmed:
                time.sleep(0.4)
                subprocess.run(["xdotool", "key", "ctrl+alt+space"], check=True)
                confirmed = True
            if "release→done" in seg:
                break
            time.sleep(0.05)
        time.sleep(0.3)

    t_start = time.time()
    for f in ["p3_open_notepad", "p3_close_notepad", "p3_volume", "p3_remind",
              "p3_list_reminders", "p3_find", "p3_open_result"]:
        say(f)
    time.sleep(0.5)

    print("\nwaiting for the reminder to fire (due in ~1 minute)…")
    deadline = time.time() + 120
    while "[Reminder] stretch" not in out.text() and time.time() < deadline:
        time.sleep(1)
    fired_after = time.time() - t_start

    rows = [json.loads(l) for l in log_path.read_text().splitlines()]
    by = {r["answers"][0]["name"] if r["answers"] else "-": r for r in rows}
    print("\n==== log.jsonl ====")
    for r in rows:
        print(f"  {r['query']!r:40} {json.dumps(r['answers'])[:80]:80} conf={r['confidence']:.2f}"
              f" route={r['route']:8} executed={r['executed']} results={json.dumps(r['results'])[:110]}")

    def res(name):
        return (by.get(name, {}).get("results") or [{}])[0]
    checks = {
        "apps: 'open notepad' launched the process":
            by.get("open_app", {}).get("executed") and notepad_marker.exists(),
        "apps: 'close notepad' -> close_window, fails cleanly off Windows":
            "only available on Windows" in str(res("close_window").get("error")),
        "apps: 'set the volume to 30' -> set_volume(30), fails cleanly off Windows":
            str(by.get("set_volume", {}).get("answers", [{}])[0].get("arguments", {}).get("level")) == "30"
            and "only available on Windows" in str(res("set_volume").get("error")),
        "reminders: set by voice after hotkey confirmation":
            by.get("set_reminder", {}).get("confirmed") is True and res("set_reminder").get("ok"),
        "reminders: listed by voice":
            any(i["text"] == "stretch" for i in res("list_reminders").get("reminders", [])),
        f"reminders: fired by the poller ({fired_after:.0f}s after start)":
            "[Reminder] stretch" in out.text(),
        "files: found 'Budget spreadsheet 2026.xlsx' by voice":
            any("Budget spreadsheet 2026.xlsx" in p for p in res("find_file").get("results", [])),
        "files: 'open result 1' opened that exact file":
            open_marker.exists() and "Budget spreadsheet 2026.xlsx" in open_marker.read_text(),
        "every utterance logged": len(rows) == 7,
    }
    print("\n==== Phase 3, four families by voice ====")
    for k, v in checks.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
