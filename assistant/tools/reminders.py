"""Reminders: SQLite store + a wake-up backend (spec 6, Phase 3).

Backends (config [reminders] backend = "auto" | "local" | "outlook"):
  * local:   Windows Task Scheduler runs `run.py --fire-reminder <id>` at the due
             time, so reminders survive reboot even if the assistant is closed.
             Registered from an XML definition (`schtasks /Create /XML`) because
             `schtasks /SD` parses dates in the machine's locale (MM/DD vs DD/MM).
             StartWhenAvailable fires missed reminders after the PC wakes up.
  * outlook: an Outlook calendar appointment with a reminder (pywin32 COM).
  * auto:    outlook if Outlook is installed, else local. The choice is logged.
While the assistant runs, a poller also fires due reminders, so on non-Windows
dev machines reminders still work in-session. Firing is idempotent: a row only
moves pending -> fired once, whichever path gets there first.

`when` is never a model-made timestamp: it is the spoken phrase, resolved by
assistant.timeparse, and the absolute time is echoed back in the confirmation.
cancel_reminder keeps the row (status=cancelled): no data is deleted (spec 8.3).
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from assistant.timeparse import expand_from_transcript, resolve

TASK_FOLDER = "WhistleAssistant"


def fmt(dt: datetime) -> str:
    hour = dt.strftime("%I").lstrip("0") or "12"
    return f"{dt:%a %d %b} {hour}:{dt:%M %p}"


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL,
                due TEXT NOT NULL, created TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                backend TEXT NOT NULL, external_id TEXT)""")

    def _conn(self):
        return sqlite3.connect(self.path, timeout=10)

    def add(self, text, due: datetime, backend) -> int:
        with self._lock, self._conn() as c:
            cur = c.execute("INSERT INTO reminders(text, due, created, backend) VALUES (?,?,?,?)",
                            (text, due.isoformat(timespec="minutes"),
                             datetime.now().isoformat(timespec="seconds"), backend))
            return cur.lastrowid

    def set_external(self, rid, external_id):
        with self._lock, self._conn() as c:
            c.execute("UPDATE reminders SET external_id=? WHERE id=?", (external_id, rid))

    def get(self, rid):
        with self._conn() as c:
            c.row_factory = sqlite3.Row
            r = c.execute("SELECT * FROM reminders WHERE id=?", (rid,)).fetchone()
            return dict(r) if r else None

    def pending(self):
        with self._conn() as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute(
                "SELECT * FROM reminders WHERE status='pending' ORDER BY due")]

    def transition(self, rid, frm, to) -> bool:
        with self._lock, self._conn() as c:
            return c.execute("UPDATE reminders SET status=? WHERE id=? AND status=?",
                             (to, rid, frm)).rowcount == 1


class NullScheduler:
    """No OS wake-up: the in-process poller fires reminders (dev / non-Windows)."""
    name = "in-process"

    def schedule(self, rid, text, due):
        return None

    def cancel(self, rid, external_id):
        pass


class TaskScheduler:
    name = "task-scheduler"

    def __init__(self, python_exe: str, script: str, workdir: str, run=subprocess.run):
        self.python_exe, self.script, self.workdir, self._run = python_exe, script, workdir, run

    def _xml(self, rid, due: datetime) -> str:
        e = escape
        return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Whistle Assistant reminder {int(rid)}</Description></RegistrationInfo>
  <Triggers><TimeTrigger><StartBoundary>{due:%Y-%m-%dT%H:%M:%S}</StartBoundary><Enabled>true</Enabled></TimeTrigger></Triggers>
  <Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <StartWhenAvailable>true</StartWhenAvailable>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author"><Exec>
    <Command>{e(self.python_exe)}</Command>
    <Arguments>"{e(self.script)}" --fire-reminder {int(rid)}</Arguments>
    <WorkingDirectory>{e(self.workdir)}</WorkingDirectory>
  </Exec></Actions>
</Task>"""

    def schedule(self, rid, text, due):
        # The reminder text is NOT in the task: only our paths and an integer id.
        name = f"{TASK_FOLDER}\\Reminder-{int(rid)}"
        fd, path = tempfile.mkstemp(suffix=".xml")
        os.close(fd)
        try:
            Path(path).write_text(self._xml(rid, due), encoding="utf-16")
            self._run(["schtasks", "/Create", "/TN", name, "/XML", path, "/F"],
                      check=True, capture_output=True, shell=False)
        finally:
            os.unlink(path)
        return name

    def cancel(self, rid, external_id):
        if external_id:
            self._run(["schtasks", "/Delete", "/TN", external_id, "/F"],
                      check=False, capture_output=True, shell=False)


class OutlookScheduler:
    name = "outlook"

    def __init__(self):
        import win32com.client
        self.app = win32com.client.Dispatch("Outlook.Application")

    def schedule(self, rid, text, due):
        appt = self.app.CreateItem(1)  # olAppointmentItem
        appt.Subject = text
        appt.Start = due.strftime("%Y-%m-%d %H:%M")
        appt.Duration = 15
        appt.ReminderSet = True
        appt.ReminderMinutesBeforeStart = 0
        appt.Categories = "Whistle Assistant"
        appt.Save()
        return appt.EntryID

    def cancel(self, rid, external_id):
        if external_id:
            # Delete only the appointment this assistant created, by its own EntryID.
            self.app.GetNamespace("MAPI").GetItemFromID(external_id).Delete()


def outlook_installed() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "Outlook.Application"))
        import win32com.client  # noqa: F401
        return True
    except Exception:
        return False


def choose_scheduler(backend: str, python_exe: str, script: str, workdir: str):
    backend = (backend or "auto").lower()
    if backend in ("auto", "outlook") and outlook_installed():
        try:
            return OutlookScheduler()
        except Exception:
            if backend == "outlook":
                raise
    if sys.platform == "win32":
        return TaskScheduler(python_exe, script, workdir)
    return NullScheduler()


class Reminders:
    def __init__(self, store: Store, scheduler, notify, now=datetime.now):
        self.store, self.scheduler, self.notify, self.now = store, scheduler, notify, now

    def resolve(self, when: str, transcript: str = ""):
        phrase = expand_from_transcript(when, transcript)
        return phrase, resolve(phrase, self.now())

    def set_reminder(self, text: str, when: str, transcript: str = "") -> dict:
        text = (text or "").strip()
        if not text:
            return {"ok": False, "error": "no reminder text"}
        phrase, due = self.resolve(when, transcript)
        if due is None:
            return {"ok": False, "error": f"couldn't work out when '{phrase}' is"}
        rid = self.store.add(text, due, self.scheduler.name)
        try:
            ext = self.scheduler.schedule(rid, text, due)
            if ext:
                self.store.set_external(rid, ext)
        except Exception as e:
            self.store.transition(rid, "pending", "failed")
            return {"ok": False, "error": f"could not schedule: {e}"}
        return {"ok": True, "id": rid, "text": text, "due": fmt(due),
                "due_iso": due.isoformat(timespec="minutes"), "backend": self.scheduler.name}

    def list_reminders(self) -> dict:
        items = [{"id": r["id"], "text": r["text"], "due": fmt(datetime.fromisoformat(r["due"]))}
                 for r in self.store.pending()]
        return {"ok": True, "reminders": items}

    def cancel_reminder(self, id: int) -> dict:
        try:
            rid = int(id)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"{id!r} is not a reminder number"}
        row = self.store.get(rid)
        if not row or row["status"] != "pending":
            return {"ok": False, "error": f"no pending reminder #{rid}"}
        self.store.transition(rid, "pending", "cancelled")
        try:
            self.scheduler.cancel(rid, row["external_id"])
        except Exception as e:
            return {"ok": True, "cancelled": rid, "warning": f"backend cleanup failed: {e}"}
        return {"ok": True, "cancelled": rid, "text": row["text"]}

    def fire(self, rid: int) -> bool:
        row = self.store.get(rid)
        if not row or not self.store.transition(rid, "pending", "fired"):
            return False
        self.notify("Reminder", row["text"])
        return True

    def fire_due(self) -> int:
        now = self.now()
        n = 0
        for r in self.store.pending():
            if datetime.fromisoformat(r["due"]) <= now and r["backend"] != "outlook":
                n += self.fire(r["id"])
        return n

    def start_poller(self, interval_s: float = 15.0) -> threading.Event:
        stop = threading.Event()

        def loop():
            while not stop.wait(interval_s):
                try:
                    self.fire_due()
                except Exception as e:
                    print(f"[reminders] poller error: {e}")
        threading.Thread(target=loop, daemon=True).start()
        return stop
