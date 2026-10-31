"""Turn data/log.jsonl into a Needle fine-tuning dataset (Phase 4.3).

Every logged row is the model's *guess*. Training on unreviewed guesses teaches
the model its own mistakes, so only rows you have reviewed are exported:
    review  -> data/corrections.jsonl  (verdict per row: ok / fixed / no-tool / drop)
    export  -> data/finetune/{train,val,test}.jsonl in Needle's format
               {"query", "tools", "answers"}
The log itself is never rewritten. Rows are keyed by timestamp + transcript.
Exports always use the *current* tool schemas, so rows logged when fewer tools
existed (Phase 2) still train against the full tool set.
"""
from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from pathlib import Path


def row_key(row: dict) -> str:
    return hashlib.sha1(f"{row.get('ts')}|{row.get('query')}".encode()).hexdigest()[:16]


def read_jsonl(path: Path) -> list[dict]:
    if not Path(path).exists():
        return []
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def load_corrections(path: Path) -> dict[str, dict]:
    out = {}
    for c in read_jsonl(path):
        out[c["key"]] = c  # last verdict wins
    return out


def command_rows(log: list[dict]) -> list[dict]:
    return [r for r in log if r.get("mode") == "command" and (r.get("query") or "").strip()]


def describe_calls(calls) -> str:
    if not calls:
        return "(no tool)"
    return "; ".join(f"{c['name']}(" + ", ".join(f"{k}={v!r}" for k, v in
                                                 (c.get("arguments") or {}).items()) + ")"
                     for c in calls)


def coerce(value: str, schema: dict):
    t = schema.get("type")
    if t == "integer":
        return int(value)
    if t == "number":
        return float(value)
    if t == "boolean":
        return value.strip().lower() in ("1", "true", "yes", "y")
    return value


def review(log_path: Path, corr_path: Path, schemas: list[dict], ask=input, say=print,
           redo: bool = False) -> int:
    """Interactive review. Returns number of rows reviewed this session."""
    done = load_corrections(corr_path)
    by_name = {s["name"]: s for s in schemas}
    names = list(by_name)
    rows = [r for r in command_rows(read_jsonl(log_path)) if redo or row_key(r) not in done]
    say(f"{len(rows)} command(s) to review. Enter=correct  n=should be no tool  "
        f"f=fix  d=drop (bad audio etc.)  s=skip  q=quit")
    n = 0
    corr_path.parent.mkdir(parents=True, exist_ok=True)
    with open(corr_path, "a", encoding="utf-8") as out:
        for r in rows:
            say(f"\nheard : {r['query']!r}\nmodel : {describe_calls(r.get('answers'))}"
                f"  (conf {r.get('confidence')}, {r.get('route')}, executed={r.get('executed')})")
            a = ask("> ").strip().lower()
            if a == "q":
                break
            if a == "s":
                continue
            rec = {"key": row_key(r), "query": r["query"]}
            if a == "":
                rec.update(verdict="ok", answers=r.get("answers") or [])
            elif a == "n":
                rec.update(verdict="no-tool", answers=[])
            elif a == "d":
                rec.update(verdict="drop", answers=None)
            elif a == "f":
                for i, nm in enumerate(names, 1):
                    say(f"  {i:2}. {nm}")
                pick = ask("tool number (0 = no tool): ").strip()
                if pick in ("", "0"):
                    rec.update(verdict="no-tool", answers=[])
                else:
                    tool = by_name[names[int(pick) - 1]]
                    args = {}
                    props = tool.get("parameters", {}).get("properties", {})
                    req = set(tool.get("parameters", {}).get("required", []))
                    for arg, sch in props.items():
                        hint = f" one of {sch['enum']}" if "enum" in sch else ""
                        v = ask(f"  {arg}{hint}{'' if arg in req else ' (optional)'}: ").strip()
                        if v:
                            args[arg] = coerce(v, sch)
                    rec.update(verdict="fixed", answers=[{"name": tool["name"], "arguments": args}])
            else:
                say("  ? skipped")
                continue
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    return n


def export(log_path: Path, corr_path: Path, schemas: list[dict], out_dir: Path,
           val: float = 0.1, test: float = 0.1, seed: int = 0, extra: list[dict] = ()) -> dict:
    corr = load_corrections(corr_path)
    examples, seen = [], set()
    for r in command_rows(read_jsonl(log_path)):
        c = corr.get(row_key(r))
        if not c or c["verdict"] == "drop":
            continue
        examples.append({"query": r["query"], "answers": c["answers"], "source": "log",
                         "verdict": c["verdict"]})
    for e in extra:
        examples.append(dict(e, source=e.get("source", "seed")))
    out = []
    for e in examples:
        k = (e["query"].strip().lower(), json.dumps(e["answers"], sort_keys=True))
        if k in seen:
            continue
        seen.add(k)
        out.append({"query": e["query"], "tools": schemas, "answers": e["answers"],
                    "_source": e["source"]})
    random.Random(seed).shuffle(out)
    n_val, n_test = int(len(out) * val), int(len(out) * test)
    splits = {"test": out[:n_test], "val": out[n_test:n_test + n_val],
              "train": out[n_test + n_val:]}
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in splits.items():
        with open(out_dir / f"{name}.jsonl", "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps({k: v for k, v in row.items() if not k.startswith("_")},
                                    ensure_ascii=False) + "\n")
    per_tool = Counter((e["answers"][0]["name"] if e["answers"] else "(no tool)") for e in out)
    sources = Counter(e["_source"] for e in out)
    return {"total": len(out), **{k: len(v) for k, v in splits.items()},
            "per_tool": dict(per_tool), "sources": dict(sources)}
