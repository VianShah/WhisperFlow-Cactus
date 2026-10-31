"""App/OS control executors. Phase 2: open_app only (Phase 3 adds the rest).

Spec 8.2: the model picks a *key* from the allowlist; we map it to a
pre-approved executable from config.toml. The model's string never reaches a
shell: no shell=True, no os.system, no eval/exec.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys


class AppLauncher:
    def __init__(self, allowlist: dict[str, str], popen=subprocess.Popen,
                 which=shutil.which, startfile=None):
        self.allowlist = {k.lower(): v for k, v in allowlist.items()}
        self._popen = popen
        self._which = which
        self._startfile = startfile or getattr(os, "startfile", None)

    @property
    def names(self) -> list[str]:
        return sorted(self.allowlist)

    def open_app(self, name: str) -> dict:
        key = str(name).strip().lower()
        exe = self.allowlist.get(key)
        if exe is None:  # never fuzzy-match an unknown name to something else
            return {"ok": False, "error": f"'{name}' is not in the app allowlist"}
        path = self._which(exe)
        if path:
            self._popen([path], shell=False, close_fds=True)
            return {"ok": True, "opened": key}
        if sys.platform == "win32" and self._startfile:
            # Pre-approved config string only; resolves App Paths (chrome, spotify).
            self._startfile(exe)
            return {"ok": True, "opened": key}
        return {"ok": False, "error": f"'{exe}' not found on this machine"}
