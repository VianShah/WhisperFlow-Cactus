"""App and OS control executors.

Spec 8.2: the model picks a *key* from the allowlist (a Literal enum in the
tool schema); we map it to a pre-approved executable from config.toml. The
model's string never reaches a shell: no shell=True, no os.system, no eval/exec.
Windows are matched by *process name*, not title (Spotify's title is the song).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys


def _process_name(exe: str) -> str:
    base = os.path.basename(exe).lower()
    return base if base.endswith(".exe") else base + ".exe"


class AppLauncher:
    def __init__(self, allowlist: dict[str, str], popen=subprocess.Popen,
                 which=shutil.which, startfile=None, api=None,
                 process_names: dict[str, str] | None = None):
        self.allowlist = {k.lower(): v for k, v in allowlist.items()}
        self._popen = popen
        self._which = which
        self._startfile = startfile or getattr(os, "startfile", None)
        self._api = api
        overrides = {k.lower(): v.lower() for k, v in (process_names or {}).items()}
        self.process_names = {k: overrides.get(k, _process_name(v))
                              for k, v in self.allowlist.items()}

    @property
    def names(self) -> list[str]:
        return sorted(self.allowlist)

    @property
    def api(self):
        if self._api is None:
            from assistant.tools.winapi import default_api
            self._api = default_api() or False
        return self._api or None

    def _key(self, name):
        key = str(name).strip().lower()
        return key if key in self.allowlist else None

    def open_app(self, name: str) -> dict:
        key = self._key(name)
        if key is None:  # never fuzzy-match an unknown name to something else
            return {"ok": False, "error": f"'{name}' is not in the app allowlist"}
        exe = self.allowlist[key]
        path = self._which(exe)
        if path:
            self._popen([path], shell=False, close_fds=True)
            return {"ok": True, "opened": key}
        if sys.platform == "win32" and self._startfile:
            # Pre-approved config string only; resolves App Paths (chrome, spotify).
            self._startfile(exe)
            return {"ok": True, "opened": key}
        return {"ok": False, "error": f"'{exe}' not found on this machine"}

    def _window_action(self, name, action):
        key = self._key(name)
        if key is None:
            return None, {"ok": False, "error": f"'{name}' is not in the app allowlist"}
        if self.api is None:
            return None, {"ok": False, "error": "window control is only available on Windows"}
        wins = self.api.windows_for(self.process_names[key])
        if not wins:
            return None, {"ok": False, "error": f"{key} has no open window"}
        return (key, wins[0]), None

    def close_window(self, name: str) -> dict:
        found, err = self._window_action(name, "close")
        if err:
            return err
        key, hwnd = found
        self.api.close_window(hwnd)  # front-most window only, like clicking X
        return {"ok": True, "closed": key}

    def focus_window(self, name: str) -> dict:
        found, err = self._window_action(name, "focus")
        if err:
            return err
        key, hwnd = found
        self.api.focus_window(hwnd)
        return {"ok": True, "focused": key}


class SystemControl:
    def __init__(self, api=None):
        self._api = api

    @property
    def api(self):
        if self._api is None:
            from assistant.tools.winapi import default_api
            self._api = default_api() or False
        return self._api or None

    def _need(self):
        return None if self.api else {"ok": False, "error": "only available on Windows"}

    VOLUME_WORDS = {"mute": 0, "muted": 0, "off": 0, "zero": 0, "half": 50,
                    "max": 100, "maximum": 100, "full": 100}

    def set_volume(self, level: int) -> dict:
        if (e := self._need()):
            return e
        raw = str(level).strip().lower().rstrip("%").strip()
        if raw in self.VOLUME_WORDS:
            level = self.VOLUME_WORDS[raw]
        else:
            try:
                level = int(raw)
            except ValueError:
                return {"ok": False, "error": f"volume {level!r} is not a number"}
        if not 0 <= level <= 100:
            return {"ok": False, "error": f"volume {level} is outside 0-100"}
        self.api.set_volume(level)
        return {"ok": True, "volume": level}

    def lock_screen(self) -> dict:
        if (e := self._need()):
            return e
        self.api.lock_screen()
        return {"ok": True}

    def sleep_display(self) -> dict:
        if (e := self._need()):
            return e
        self.api.sleep_display()
        return {"ok": True}
