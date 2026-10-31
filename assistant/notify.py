"""User feedback: what the assistant heard and what it did (spec Phase 2.5).

Always prints a console line. On Windows, also shows a toast via win11toast
when installed. Toasts are best-effort and never block or crash the pipeline.
"""
from __future__ import annotations

import sys
import threading


def _toast(title: str, body: str) -> None:
    try:
        from win11toast import notify as win_notify
    except Exception:
        return
    try:
        win_notify(title, body, app_id="Whistle Assistant")
    except Exception:
        pass


def notify(title: str, body: str) -> None:
    print(f"[{title}] {body}", flush=True)
    if sys.platform == "win32":
        threading.Thread(target=_toast, args=(title, body), daemon=True).start()
