"""Append-only JSONL log of every command utterance (spec 3.6, 8.4).

Rows use Needle's fine-tune field names (query, tools, answers, reasoning) so
the file feeds `needle finetune` in Phase 4 directly. `answers` is what the
model produced; set `corrected_answers` by hand on wrong rows before training.
Dictation is not logged by default: it is private prose and useless for
training the intent model (config [log] include_dictation).
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path


class Logbook:
    def __init__(self, path: str | Path, include_dictation: bool = False):
        self.path = Path(path)
        self.include_dictation = include_dictation
        self._lock = threading.Lock()

    def write(self, row: dict) -> None:
        if row.get("mode") == "dictate" and not self.include_dictation:
            return
        row = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **row}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(row, ensure_ascii=False, default=str)
        with self._lock, open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
