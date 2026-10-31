"""Whistle Assistant entry point.

  python run.py --setup          one-time: download engine + weights (needs internet)
  python run.py                  push-to-talk: hold Ctrl+Alt+D, speak, release
  python run.py --file x.wav     headless: transcribe a 16 kHz WAV (no mic/hotkeys)
  python run.py --file x.wav --command   ...and run it through the command path
  python run.py --text "open notepad"     command path from typed text (no audio)
  add --dry-run to any command mode to log/decide without executing anything
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
    s.transcribe(np.zeros(16_000, dtype=np.float32))  # Whistle engine + weights
    import needle

    @needle.tool
    def ping():
        "Reply to a ping."
        return {}
    agent = needle.Needle(tools=[ping], stateless=True)  # Needle 3 engine + weights
    agent.complete("ping")
    agent.close()
    print("Models cached. The assistant now runs fully offline.")
    return 0


def build_reminders(cfg):
    from assistant.config import ROOT
    from assistant.notify import notify
    from assistant.tools import reminders as rem

    rcfg = cfg.get("reminders", {})
    py = sys.executable
    if sys.platform == "win32" and py.lower().endswith("python.exe"):
        py = py[:-len("python.exe")] + "pythonw.exe"  # no console window when firing
    sched = rem.choose_scheduler(rcfg.get("backend", "auto"), py,
                                 str(ROOT / "run.py"), str(ROOT))
    print(f"[reminders] backend: {sched.name}")
    return rem.Reminders(rem.Store(ROOT / rcfg.get("db", "data/reminders.db")), sched, notify)


def build_command(cfg, confirm, dry_run=False, reminders=None):
    from assistant.apps_config import allowlist
    from assistant.intent import IntentEngine, Registry
    from assistant.logbook import Logbook
    from assistant.pipeline import CommandPipeline
    from assistant.tools.apps import AppLauncher, SystemControl
    from assistant.tools.clock import get_time
    from assistant.tools.files import FileSearch
    from assistant.config import ROOT

    fcfg = cfg.get("files", {})
    files = FileSearch(fcfg.get("everything_cli", "es.exe"), fcfg.get("fallback_roots", []),
                       fcfg.get("max_results", 10), fcfg.get("timeout_s", 4.0))
    print(f"[files] backend: {files.backend}")
    registry = Registry(AppLauncher(allowlist(cfg),
                                    process_names=cfg.get("apps", {}).get("process_names")),
                        get_time, system=SystemControl(),
                        reminders=reminders or build_reminders(cfg), files=files)
    engine = IntentEngine(registry, cfg["intent"]["act_threshold"],
                          cfg["intent"]["confirm_threshold"],
                          cfg["intent"].get("confirm_floor", {}))
    log = Logbook(ROOT / cfg.get("log", {}).get("path", "data/log.jsonl"),
                  cfg.get("log", {}).get("include_dictation", False))
    return CommandPipeline(engine, log, confirm, dry_run=dry_run)


def _console_confirm(d) -> bool:
    try:
        return input("  confirm? [y/N] ").strip().lower() == "y"
    except EOFError:
        return False


def run_text(queries: list[str], dry_run: bool) -> int:
    from assistant import config
    pipe = build_command(config.load(), _console_confirm, dry_run)
    for q in queries:
        pipe.handle(q)
    return 0


def run_file(paths: list[str], command: bool = False, dry_run: bool = False) -> int:
    from assistant import config, stt
    cfg = config.load()
    s = stt.SpeechToText(cfg["speech"]["language"], config.load_vocabulary(cfg))
    pipe = build_command(cfg, _console_confirm, dry_run) if command else None
    for p in paths:
        t = s.transcribe(p)
        print(_line(t).replace("[dictate]", "[command]" if command else "[dictate]"))
        if pipe:
            pipe.handle(t.text, t.latency_ms)
    return 0


def run_hotkeys(no_paste: bool, dry_run: bool = False) -> int:
    from assistant import config, stt
    from assistant.audio import Recorder
    from assistant.hotkeys import PushToTalk
    from assistant.tools.dictation import paste_text

    cfg = config.load()
    speech = stt.SpeechToText(cfg["speech"]["language"], config.load_vocabulary(cfg))
    rec = Recorder(cfg["speech"].get("max_seconds", 30))
    dcfg = cfg.get("dictation", {})
    busy = threading.Lock()
    confirm_timeout = cfg["intent"].get("confirm_timeout_s", 6)
    pending = {"event": None, "answer": False}

    def chord_confirm(_decision) -> bool:
        # Confirm = press the command hotkey again; Esc or timeout = cancel.
        # Not Enter/Y: those keystrokes would also reach the focused app.
        ev = threading.Event()
        pending.update(event=ev, answer=False)
        ev.wait(confirm_timeout)
        pending["event"] = None
        return pending["answer"]

    reminders = build_reminders(cfg)
    missed = reminders.fire_due()  # anything that came due while we were off
    if missed:
        print(f"[reminders] fired {missed} missed reminder(s)")
    reminders.start_poller()
    command = build_command(cfg, chord_confirm, dry_run, reminders)
    active = {"mode": None}

    def on_press(mode):
        if pending["event"] is not None:  # answering a confirmation, not recording
            pending["answer"] = mode == "command"
            pending["event"].set()
            return
        if busy.locked():
            return
        active["mode"] = mode
        rec.start()
        print(f"[{mode}] listening…", flush=True)

    def on_escape():
        if pending["event"] is not None:
            pending["answer"] = False
            pending["event"].set()

    def on_release(mode):
        if mode != active["mode"] or not rec.recording:
            return
        active["mode"] = None
        released = time.perf_counter()
        audio = rec.stop()

        def work():
            with busy:
                t = speech.transcribe(audio)
                if mode == "dictate":
                    pasted = None if no_paste else paste_text(
                        t.text,
                        paste_delay_ms=dcfg.get("paste_delay_ms", 40),
                        restore_delay_ms=dcfg.get("restore_delay_ms", 250))
                    e2e = (time.perf_counter() - released) * 1000
                    print(_line(t, pasted) + f" | release→text {e2e:.0f} ms", flush=True)
                else:
                    print(_line(t).replace("[dictate]", "[command]"), flush=True)
                    row = command.handle(t.text, t.latency_ms)
                    e2e = (time.perf_counter() - released) * 1000
                    print(f"[command] route={row['route']} | intent {row['intent_ms']} ms"
                          f" | release→done {e2e:.0f} ms", flush=True)
        threading.Thread(target=work, daemon=True).start()

    # Warm the engine so the first utterance isn't slowed by model load.
    import numpy as np
    speech.transcribe(np.zeros(1600, dtype=np.float32) + 1e-6)
    command.engine.decide("warm up")
    print(f"Ready. Hold {cfg['hotkeys']['dictate']} to dictate, "
          f"{cfg['hotkeys']['command']} for a command. Ctrl+C to quit.")
    PushToTalk({"dictate": cfg["hotkeys"]["dictate"],
                "command": cfg["hotkeys"]["command"]}, on_press, on_release,
               on_escape=on_escape).run_forever()
    return 0


def fire_reminder(rid: int) -> int:
    """Entry point for Task Scheduler: show reminder <rid> once."""
    from assistant import config
    r = build_reminders(config.load())
    r.fire(rid)
    time.sleep(3)  # let the toast thread show before the process exits
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--setup", action="store_true", help="download models once")
    ap.add_argument("--file", nargs="+", metavar="WAV", help="transcribe WAV file(s)")
    ap.add_argument("--no-paste", action="store_true", help="print only, don't paste")
    ap.add_argument("--text", nargs="+", metavar="QUERY", help="run typed command(s)")
    ap.add_argument("--command", action="store_true", help="with --file: command path")
    ap.add_argument("--dry-run", action="store_true", help="decide and log, never execute")
    ap.add_argument("--fire-reminder", type=int, metavar="ID", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.setup:
        return setup()
    if a.fire_reminder is not None:
        return fire_reminder(a.fire_reminder)
    if a.text:
        return run_text(a.text, a.dry_run)
    if a.file:
        return run_file(a.file, a.command, a.dry_run)
    return run_hotkeys(a.no_paste, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
