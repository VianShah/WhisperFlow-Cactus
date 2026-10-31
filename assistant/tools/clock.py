"""get_time executor."""
from __future__ import annotations

from datetime import datetime


def get_time(now=None) -> dict:
    now = now or datetime.now()
    hour = now.strftime("%I").lstrip("0") or "12"
    return {"time": f"{hour}:{now:%M %p}", "date": f"{now:%A %d %B}"}
