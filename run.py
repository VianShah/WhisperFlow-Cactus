"""Whistle Assistant entry point.

  python run.py --setup          one-time: download engine + weights (needs internet)
  python run.py                  push-to-talk: hold Ctrl+Alt+D, speak, release
  python run.py --file x.wav     headless: transcribe a 16 kHz WAV (no mic/hotkeys)
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time


def _line(t, pasted: bool | None = None) -> str:
    tps = f"{t.decode_tps:.0f} tok/s" if t.decode_tps else "- tok/s"
    ttft = f"ttft {t.ttft_ms:.0f} ms" if t.ttft_ms is not None else "ttft -"
    tail = "" if pasted is None else (" | pasted" if pasted else " | (empty, nothing pasted)")
    return (f"[dictate] {t.text!r} | audio {t.audio_seconds:.1f}s | "
            f"stt {t.latency_ms:.0f} ms | {ttft} | {tps}{tail}")


def setup() -> int:
    os.environ["HF_HUB_OFFLINE"] = "0"
    from assistant import config, stt
    cfg = config.load()
    s = stt.SpeechToText(cfg["speech"]["language"])
    import numpy as np
    s.transcribe(np.zeros(16_000, dtype=np.float32))  # forces engine + weights fetch
    print("Models cached. The assistant now runs fully offline.")
    return 0


def run_file(paths: list[str]) -> int:
    from assistant import config, stt
    cfg = config.load()
    s = stt.SpeechToText(cfg["speech"]["language"], config.load_vocabulary(cfg))
    for p in paths:
        print(_line(s.transcribe(p)))
    return 0


def run_hotkeys(no_paste: bool) -> int:
    from assistant import config, stt
    from assistant.audio import Recorder
    from assistant.hotkeys import PushToTalk
    from assistant.tools.dictation import paste_text

    cfg = config.load()
    speech = stt.SpeechToText(cfg["speech"]["language"], config.load_vocabulary(cfg))
    rec = Recorder(cfg["speech"].get("max_seconds", 30))
    dcfg = cfg.get("dictation", {})
    busy = threading.Lock()

    def on_press(mode):
        if mode != "dictate":
            print(f"[{mode}] not implemented until Phase 2")
            return
        if busy.locked():
            return
        rec.start()
        print("[dictate] listening…", flush=True)

    def on_release(mode):
        if mode != "dictate" or not rec.recording:
            return
        released = time.perf_counter()
        audio = rec.stop()

        def work():
            with busy:
                t = speech.transcribe(audio)
                pasted = None if no_paste else paste_text(
                    t.text,
                    paste_delay_ms=dcfg.get("paste_delay_ms", 40),
                    restore_delay_ms=dcfg.get("restore_delay_ms", 250))
                e2e = (time.perf_counter() - released) * 1000
                print(_line(t, pasted) + f" | release→text {e2e:.0f} ms", flush=True)
        threading.Thread(target=work, daemon=True).start()

    # Warm the engine so the first utterance isn't slowed by model load.
    import numpy as np
    speech.transcribe(np.zeros(1600, dtype=np.float32) + 1e-6)
    print(f"Ready. Hold {cfg['hotkeys']['dictate']} and speak. Ctrl+C to quit.")
    PushToTalk({"dictate": cfg["hotkeys"]["dictate"],
                "command": cfg["hotkeys"]["command"]}, on_press, on_release).run_forever()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--setup", action="store_true", help="download models once")
    ap.add_argument("--file", nargs="+", metavar="WAV", help="transcribe WAV file(s)")
    ap.add_argument("--no-paste", action="store_true", help="print only, don't paste")
    a = ap.parse_args(argv)
    if a.setup:
        return setup()
    if a.file:
        return run_file(a.file)
    return run_hotkeys(a.no_paste)


if __name__ == "__main__":
    sys.exit(main())
