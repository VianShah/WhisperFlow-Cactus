"""Grow data/vocabulary.txt from what you actually say (Phase 4.4).

Keyword biasing is the cheapest accuracy win: in Phase 2, "Open notepad" was
heard as "Open notes, Tan" without it and correctly with it. Candidates come
from executed/reviewed commands: app names, file-search words, and proper nouns
in reminder texts (Whistle capitalises names), counted across the log.
"""
from __future__ import annotations

import re
from collections import Counter

STOP = set("""a an the to of in on at for by with and or but is are be me my i you it
this that these those what when where who how please can could would will just now
today tomorrow tonight morning afternoon evening minute minutes hour hours day days
week remind reminder reminders open close find search file files result number set
volume screen display lock switch focus start launch quit exit call""".split())


def suggest(rows: list[dict], existing: list[str], app_names: dict[str, str] | None = None,
            min_count: int = 2) -> list[tuple[str, int]]:
    have = {w.lower() for w in existing}
    counts: Counter = Counter()
    for r in rows:
        if r.get("mode") != "command" or not (r.get("executed") or r.get("verdict") in ("ok", "fixed")):
            continue
        for c in r.get("answers") or []:
            args = c.get("arguments") or {}
            if c["name"] in ("open_app", "close_window", "focus_window") and args.get("name"):
                counts[(app_names or {}).get(args["name"], args["name"])] += 1
            if c["name"] == "find_file" and args.get("query"):
                for w in re.findall(r"[A-Za-z][\w'-]{2,}", args["query"]):
                    if w.lower() not in STOP:
                        counts[w] += 1
            if c["name"] == "set_reminder" and args.get("text"):
                for w in re.findall(r"\b[A-Z][a-z]{2,}\b", args["text"]):
                    if w.lower() not in STOP:
                        counts[w] += 1
    return [(w, n) for w, n in counts.most_common()
            if n >= min_count and w.lower() not in have]
