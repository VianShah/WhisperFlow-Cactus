"""Accuracy + routing report for the intent layer on the real models.

    python tests/eval_intent.py            # typed text -> Needle
    python tests/eval_intent.py --weights checkpoints/tuned.cact   # a fine-tuned model
    python tests/eval_intent.py --cases data/finetune/test.jsonl   # an exported split
    python tests/eval_intent.py --voice    # espeak-ng speech -> Whistle -> Needle
    PIPER_VOICE=en_US-lessac-medium.onnx python tests/eval_intent.py --voice
                                           # neural Piper voice (far closer to a human)

Prints, per tool: correct tool+args, and how the correct calls would be routed
(act / confirm / refuse). Does not write data/log.jsonl. Voice mode needs
espeak-ng + ffmpeg and synthesises audio in memory only (spec 8.4).
"""
from __future__ import annotations

import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def speak(text):
    """Synthesise speech in memory -> 16 kHz mono float32."""
    import json
    import os
    import numpy as np
    voice = os.environ.get("PIPER_VOICE")
    if voice:
        raw = subprocess.run([sys.executable, "-m", "piper", "-m", voice, "--output-raw"],
                             input=text.encode(), capture_output=True, check=True).stdout
        rate = json.load(open(voice + ".json"))["audio"]["sample_rate"]
        src = ["-f", "s16le", "-ar", str(rate), "-ac", "1", "-i", "pipe:0"]
    else:
        raw = subprocess.run(["espeak-ng", "-v", "en-us", "-s", "150", "--stdout", text],
                             capture_output=True, check=True).stdout
        src = ["-i", "pipe:0"]
    pcm = subprocess.run(["ffmpeg", "-loglevel", "error", *src, "-ar", "16000",
                          "-ac", "1", "-f", "s16le", "pipe:1"], input=raw,
                         capture_output=True, check=True).stdout
    return np.frombuffer(pcm, "<i2").astype("float32") / 32768


def main():
    import tempfile
    import pytest
    import test_intent_model as T
    from assistant import config
    from assistant.apps_config import allowlist
    from assistant.intent import IntentEngine, Registry
    from assistant.stt import SpeechToText
    from assistant.tools.apps import AppLauncher, SystemControl
    from assistant.tools.files import FileSearch
    from assistant.tools.reminders import NullScheduler, Reminders, Store

    voice = "--voice" in sys.argv
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", action="store_true")
    ap.add_argument("--weights")
    ap.add_argument("--cases", type=Path)
    a = ap.parse_args()
    cfg = config.load()
    tmp = Path(tempfile.mkdtemp())
    reg = Registry(AppLauncher(allowlist(cfg), api=False), lambda: {}, SystemControl(api=False),
                   Reminders(Store(tmp / "r.db"), NullScheduler(), lambda *a: None),
                   FileSearch(everything_cli=None))
    eng = IntentEngine(reg, cfg["intent"]["act_threshold"], cfg["intent"]["confirm_threshold"],
                       weights=a.weights)
    stt = SpeechToText("en", config.load_vocabulary(cfg)) if voice else None

    if a.cases:
        import json
        rows = [json.loads(l) for l in a.cases.read_text().splitlines() if l.strip()]
        all_cases = [(r["query"], r["answers"][0]["name"] if r["answers"] else None,
                      r["answers"][0]["arguments"] if r["answers"] else None) for r in rows]
    else:
        cases = [c.values if hasattr(c, "values") else c for c in T.CASES]
        all_cases = cases + [(n, None, None) for n in T.NONSENSE]
    stats = defaultdict(lambda: defaultdict(int))
    misses = []
    for q, tool, args in all_cases:
        heard = stt.transcribe(speak(q)).text if voice else q
        d = eng.decide(heard)
        key = tool or "(nonsense)"
        s = stats[key]
        s["n"] += 1
        if tool is None:
            s["safe"] += d.route not in ("act", "confirm")
            if d.route in ("act", "confirm"):
                misses.append((q, heard, d))
            continue
        got = {k: str(v).lower() for k, v in (d.calls[0]["arguments"] if d.calls else {}).items()}
        ok = [c["name"] for c in d.calls] == [tool] and all(got.get(k) == str(v).lower()
                                                             for k, v in args.items())
        s["correct"] += ok
        if ok:
            s[d.route] += 1
        else:
            misses.append((q, heard, d))
            s["wrong_" + d.route] += 1

    print(f"\n{'voice' if voice else 'text'} eval — act>={eng.act_threshold}, "
          f"confirm>={eng.confirm_threshold}"
          f"{' — weights ' + a.weights if a.weights else ' — base model'}"
          f"{' — cases ' + str(a.cases) if a.cases else ''}\n")
    print(f"{'tool':16} {'n':>3} {'correct':>8} {'act':>5} {'confirm':>8} {'refuse':>7} "
          f"{'wrong&run':>10}")
    tot = defaultdict(int)
    for tool, s in stats.items():
        if tool == "(nonsense)":
            continue
        wrong_run = s["wrong_act"] + s["wrong_confirm"]
        print(f"{tool:16} {s['n']:>3} {s['correct']:>8} {s['act']:>5} {s['confirm']:>8} "
              f"{s['refuse'] + s['none']:>7} {wrong_run:>10}")
        for k in ("n", "correct", "act", "confirm"):
            tot[k] += s[k]
        tot["refuse"] += s["refuse"] + s["none"]
        tot["wrong_run"] += wrong_run
    print(f"{'TOTAL':16} {tot['n']:>3} {tot['correct']:>8} {tot['act']:>5} {tot['confirm']:>8} "
          f"{tot['refuse']:>7} {tot['wrong_run']:>10}")
    ns = stats["(nonsense)"]
    print(f"\nnonsense: {ns['safe']}/{ns['n']} took no action")
    tool_only = sum(s["correct"] for k, s in stats.items() if k != "(nonsense)")
    print(f"tool+args correct regardless of confidence: {tool_only}/{tot['n']}")
    print("\nmisses:")
    for q, heard, d in misses:
        h = f" (heard {heard!r})" if voice and heard.lower().strip(".?! ") != q else ""
        print(f"  {q!r}{h} -> {d.calls} conf={d.confidence} route={d.route}")


if __name__ == "__main__":
    main()
