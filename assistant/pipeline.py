"""Command path: transcript -> Needle -> gate -> (confirm) -> executors -> notify + log."""
from __future__ import annotations

from typing import Callable

from assistant.intent import ACT, CONFIRM, Decision, IntentEngine
from assistant.notify import notify as default_notify


def describe(calls: list[dict]) -> str:
    out = []
    for c in calls:
        args = ", ".join(f"{k}={v!r}" for k, v in (c.get("arguments") or {}).items())
        out.append(f"{c.get('name')}({args})")
    return "; ".join(out)


def summarise(calls: list[dict], results: list[dict]) -> str:
    parts = []
    for c, r in zip(calls, results):
        if isinstance(r, dict) and r.get("ok") is False:
            parts.append(f"failed: {r.get('error')}")
        elif c.get("name") == "get_time":
            parts.append(f"It's {r['time']}, {r['date']}")
        elif c.get("name") == "open_app":
            parts.append(f"Opened {r.get('opened')}")
        else:
            parts.append(f"{c.get('name')} done")
    return "; ".join(parts)


class CommandPipeline:
    def __init__(self, engine: IntentEngine, logbook, confirm: Callable[[Decision], bool],
                 notify: Callable[[str, str], None] = default_notify, dry_run: bool = False):
        self.engine = engine
        self.logbook = logbook
        self.confirm = confirm
        self.notify = notify
        self.dry_run = dry_run

    def handle(self, transcript: str, stt_ms: float | None = None) -> dict:
        d = self.engine.decide(transcript)
        heard = f"Heard: {d.query!r}" if d.query else "Heard nothing"
        executed, confirmed, results = False, None, []

        if d.route == ACT or d.route == CONFIRM:
            if d.route == CONFIRM:
                self.notify("Confirm?", f"{heard} -> {describe(d.calls)} "
                            f"(confidence {d.confidence:.2f}). Press the command hotkey "
                            f"again to confirm; Esc or wait to cancel.")
                confirmed = bool(self.confirm(d))
            if d.route == ACT or confirmed:
                if self.dry_run:
                    results = [{"ok": True, "dry_run": True} for _ in d.calls]
                    self.notify("Command", f"{heard} -> would run {describe(d.calls)}")
                else:
                    results = self.engine.registry.dispatch(d.calls)
                    self.notify("Command", f"{heard} -> {summarise(d.calls, results)}")
                executed = not self.dry_run
            else:
                self.notify("Cancelled", f"{heard} -> nothing done")
        else:
            self.notify("No action", f"{heard} -> {d.why}")

        row = {
            "mode": "command",
            "query": d.query,
            "answers": d.calls,
            "reasoning": d.reasoning,
            "tools": self.engine.registry.schemas,
            "confidence": d.confidence,
            "suppressed_calls": d.suppressed,
            "validation": d.validation,
            "route": d.route,
            "why": d.why,
            "confirmed": confirmed,
            "executed": executed,
            "results": results,
            "stt_ms": round(stt_ms) if stt_ms is not None else None,
            "intent_ms": round(d.latency_ms),
        }
        self.logbook.write(row)
        return row
