"""Start with Windows (Phase 4.2): a shortcut in the user's Startup folder.

Chosen over a scheduled task: per-user, no admin, visible and removable in
Settings > Apps > Startup and by deleting one file. Runs pythonw (no console).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

NAME = "Whistle Assistant.lnk"


def startup_dir() -> Path:
    appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def pythonw(exe: str = sys.executable) -> str:
    p = Path(exe)
    cand = p.with_name("pythonw.exe")
    return str(cand) if p.name.lower() == "python.exe" and cand.exists() else str(p)


class Autostart:
    def __init__(self, script: str, workdir: str, folder: Path | None = None,
                 shell_factory=None, python_exe: str | None = None):
        self.script, self.workdir = script, workdir
        self.folder = folder or startup_dir()
        self._shell_factory = shell_factory
        self.python_exe = python_exe or pythonw()

    @property
    def path(self) -> Path:
        return self.folder / NAME

    def is_enabled(self) -> bool:
        return self.path.exists()

    def _shell(self):
        if self._shell_factory:
            return self._shell_factory()
        import win32com.client
        return win32com.client.Dispatch("WScript.Shell")

    def enable(self) -> Path:
        self.folder.mkdir(parents=True, exist_ok=True)
        lnk = self._shell().CreateShortCut(str(self.path))
        lnk.TargetPath = self.python_exe
        lnk.Arguments = f'"{self.script}"'
        lnk.WorkingDirectory = self.workdir
        lnk.Description = "Whistle Assistant (offline voice assistant)"
        lnk.save()
        return self.path

    def disable(self) -> bool:
        if self.path.exists():
            self.path.unlink()
            return True
        return False


def for_this_install():
    if sys.platform != "win32":
        return None
    from assistant.config import ROOT
    return Autostart(str(ROOT / "run.py"), str(ROOT))
