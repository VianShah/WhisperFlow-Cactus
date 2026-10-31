"""File search and open (spec 6, Phase 3).

find_file: Everything's es.exe when present (instant), else a bounded os.walk
over configured folders with a result cap and timeout.

open_file takes a *result number* from the last find_file in this session, not
a path: nobody can speak a path, and it makes the spec rule ("only open paths a
prior find_file returned") structural. Executable types are never opened (that
would run them); they are revealed in Explorer instead.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Opening these runs code. Show them in Explorer instead.
EXECUTABLE_EXTS = {
    ".exe", ".com", ".bat", ".cmd", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse",
    ".wsf", ".wsh", ".msi", ".msp", ".scr", ".pif", ".lnk", ".url", ".hta", ".cpl",
    ".jar", ".reg", ".inf", ".application", ".appref-ms", ".gadget", ".msc", ".sh",
    ".py", ".pyw", ".dll", ".sys", ".scf", ".iso", ".img", ".vhd", ".vhdx",
}
SKIP_DIRS = {"node_modules", "__pycache__", "$recycle.bin", "appdata", ".git", ".venv"}


def expand_root(root: str) -> str:
    user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    return os.path.expanduser(os.path.expandvars(root.replace("%USERNAME%", user)))


def sanitize_query(q: str) -> str:
    """Keep es.exe from reading the spoken query as a command-line switch
    (e.g. '-export-csv'): strip leading -,/ from every word, drop odd chars."""
    words = []
    for w in str(q).split():
        w = w.lstrip("-/\\")
        w = re.sub(r"[^\w.\- ']", "", w, flags=re.UNICODE)
        if w:
            words.append(w)
    return " ".join(words)[:100]


class FileSearch:
    def __init__(self, everything_cli="es.exe", roots=(), max_results=10, timeout_s=4.0,
                 which=shutil.which, run=subprocess.run, opener=None, revealer=None):
        self.es = which(everything_cli) if everything_cli else None
        self.roots = [expand_root(r) for r in roots]
        self.max_results = max_results
        self.timeout_s = timeout_s
        self._run = run
        self._opener = opener or _default_open
        self._revealer = revealer or _default_reveal
        self.last_results: list[str] = []

    @property
    def backend(self) -> str:
        return "everything" if self.es else "walk"

    def find_file(self, query: str, limit: int = 10) -> dict:
        q = sanitize_query(query)
        if not q:
            return {"ok": False, "error": "empty search"}
        try:
            limit = max(1, min(int(limit), self.max_results))
        except (TypeError, ValueError):
            limit = self.max_results
        t0 = time.perf_counter()
        if self.es:
            paths = self._everything(q, limit)
            note = None
        else:
            paths, timed_out = self._walk(q, limit)
            note = ("slow fallback search; install Everything (voidtools.com) and put es.exe "
                    "on PATH" + ("; stopped at the time limit" if timed_out else ""))
        self.last_results = paths
        out = {"ok": True, "query": q, "results": paths, "backend": self.backend,
               "ms": round((time.perf_counter() - t0) * 1000)}
        if note:
            out["note"] = note
        return out

    def _everything(self, q, limit):
        # /a-d = files only. Query is one argv element; never a shell.
        r = self._run([self.es, "-n", str(limit), "/a-d", q], capture_output=True,
                      text=True, timeout=self.timeout_s, shell=False)
        return [l.strip() for l in r.stdout.splitlines() if l.strip()][:limit]

    def _walk(self, q, limit):
        words = [w.lower() for w in q.split()]
        hits, deadline, timed_out = [], time.monotonic() + self.timeout_s, False
        for root in self.roots:
            if not os.path.isdir(root):
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                if time.monotonic() > deadline:
                    timed_out = True
                    break
                dirnames[:] = [d for d in dirnames
                               if not d.startswith(".") and d.lower() not in SKIP_DIRS]
                for f in filenames:
                    name = f.lower()
                    if all(w in name for w in words):
                        hits.append(os.path.join(dirpath, f))
                if len(hits) >= limit * 20:
                    break
        hits.sort(key=lambda p: _mtime(p), reverse=True)
        return hits[:limit], timed_out

    def open_file(self, number: int) -> dict:
        try:
            n = int(number)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"{number!r} is not a result number"}
        if not self.last_results:
            return {"ok": False, "error": "search for a file first"}
        if not 1 <= n <= len(self.last_results):
            return {"ok": False, "error": f"there is no result {n} (1-{len(self.last_results)})"}
        path = self.last_results[n - 1]
        if not os.path.isfile(path):
            return {"ok": False, "error": f"{Path(path).name} no longer exists"}
        if Path(path).suffix.lower() in EXECUTABLE_EXTS:
            self._revealer(path)
            return {"ok": True, "revealed": path,
                    "note": "program/script files are shown in Explorer, not run"}
        self._opener(path)
        return {"ok": True, "opened": path}


def _mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0


def _default_open(path):
    if sys.platform == "win32":
        os.startfile(path)  # default app for this file type; path came from our search
    else:
        subprocess.Popen(["xdg-open", path], shell=False)


def _default_reveal(path):
    if sys.platform == "win32":
        subprocess.Popen(["explorer.exe", "/select,", path], shell=False)
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)], shell=False)
