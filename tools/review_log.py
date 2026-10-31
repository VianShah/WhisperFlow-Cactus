"""Review logged commands, then export a Needle fine-tuning dataset.

    python tools/review_log.py stats
    python tools/review_log.py review [--redo]
    python tools/review_log.py export [--seed-data tools/seed_examples.jsonl]
    python tools/review_log.py vocab [--apply]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def schemas(cfg):
    from assistant.apps_config import allowlist
    from assistant.intent import Registry
    from assistant.tools.apps import AppLauncher, SystemControl
    from assistant.tools.files import FileSearch
    from assistant.tools.reminders import NullScheduler, Reminders, Store
    import tempfile
    rem = Reminders(Store(Path(tempfile.mkdtemp()) / "r.db"), NullScheduler(), lambda *a: None)
    reg = Registry(AppLauncher(allowlist(cfg), api=False), lambda: {}, SystemControl(api=False),
                   reminders=rem, files=FileSearch(everything_cli=None))
    return reg.schemas


def main(argv=None):
    import assistant  # noqa: F401
    from assistant import config, dataset, vocab
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["stats", "review", "export", "vocab"])
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--seed-data", type=Path)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "finetune")
    a = ap.parse_args(argv)
    cfg = config.load()
    log = ROOT / cfg.get("log", {}).get("path", "data/log.jsonl")
    corr = ROOT / "data" / "corrections.jsonl"

    if a.cmd == "stats":
        rows = dataset.command_rows(dataset.read_jsonl(log))
        c = dataset.load_corrections(corr)
        verdicts = Counter(c[dataset.row_key(r)]["verdict"] for r in rows if dataset.row_key(r) in c)
        routes = Counter(r.get("route") for r in rows)
        print(f"{len(rows)} logged commands; reviewed {sum(verdicts.values())}: {dict(verdicts)}")
        print(f"routes: {dict(routes)}")
        print("Spec: fine-tune once a few hundred reviewed examples exist.")
    elif a.cmd == "review":
        n = dataset.review(log, corr, schemas(cfg), redo=a.redo)
        print(f"\nreviewed {n}; saved to {corr}")
    elif a.cmd == "export":
        extra = dataset.read_jsonl(a.seed_data) if a.seed_data else []
        info = dataset.export(log, corr, schemas(cfg), a.out, extra=extra)
        print(json.dumps(info, indent=2))
        if info["total"] < 100:
            print("warning: under 100 examples; Needle fine-tunes on 100-10,000.")
    elif a.cmd == "vocab":
        from assistant.apps_config import allowlist
        rows = dataset.read_jsonl(log)
        c = dataset.load_corrections(corr)
        for r in rows:
            k = dataset.row_key(r)
            if k in c and c[k]["verdict"] in ("ok", "fixed"):
                r["answers"], r["verdict"] = c[k]["answers"], c[k]["verdict"]
        vfile = ROOT / cfg["speech"].get("vocabulary_file", "data/vocabulary.txt")
        sug = vocab.suggest(rows, config.load_vocabulary(cfg),
                            {k: v for k, v in cfg.get("speech", {}).get("app_display_names", {}).items()})
        if not sug:
            print("no new vocabulary suggestions")
        for w, n in sug:
            print(f"  {w}  (x{n})")
        if a.apply and sug:
            with open(vfile, "a", encoding="utf-8") as fh:
                for w, _ in sug:
                    fh.write(w + "\n")
            print(f"appended {len(sug)} to {vfile}")


if __name__ == "__main__":
    main()
