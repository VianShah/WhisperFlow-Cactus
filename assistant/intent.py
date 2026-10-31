"""Needle 3 intent layer: transcript -> gated, typed tool calls.

Verified against cactus-needle 3.2.8 (see BUILD.md 3.0):
  * Needle.run() executes tools *before* returning confidence, so the spec 8.1
    gate is impossible with it. We call Needle.complete() (no execution), gate,
    then dispatch ourselves.
  * stateless=True: each utterance is independent; otherwise prior turns stay
    in context and accuracy drops.
  * open_app's `name` is a Literal enum built from the config allowlist. Probed
    on the real model this turned nonsense ("purple monkey dishwasher",
    "open photoshop") into empty function_calls instead of a low-confidence
    guess, and mapped "open vs code" -> "vscode".
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Annotated, Callable, Literal

import assistant  # noqa: F401  (telemetry/offline env before needle import)

ACT, CONFIRM, REFUSE, NONE = "act", "confirm", "refuse", "none"


@dataclass
class Decision:
    query: str
    calls: list[dict]
    confidence: float | None
    reasoning: str = ""
    suppressed: list[dict] = field(default_factory=list)
    validation: dict = field(default_factory=dict)
    latency_ms: float = 0.0
    route: str = NONE
    why: str = ""


def gate(d: Decision, act_threshold: float, confirm_threshold: float,
         always_confirm: frozenset | set = frozenset(),
         confirm_floor: dict | None = None) -> Decision:
    """Spec 8.1. Pure function; sets d.route and d.why.

    confirm_floor optionally lowers the refuse/confirm boundary per tool (config
    [intent.confirm_floor]). It can only move a call from "refuse" to "confirm"
    (the user still has to approve it); it never makes anything run unasked."""
    if confirm_floor and d.calls:
        floors = [min(confirm_floor.get(c.get("name"), confirm_threshold), confirm_threshold)
                  for c in d.calls]
        confirm_threshold = max(floors)
    if not d.calls:
        d.route, d.why = NONE, "model chose no tool"
    elif d.confidence is None:
        # Local fine-tunes drop the confidence head: never act without a score.
        d.route, d.why = REFUSE, "no confidence score (uncalibrated weights)"
    elif d.validation.get("ungrounded"):
        d.route, d.why = REFUSE, "ungrounded arguments: " + ", ".join(d.validation["ungrounded"])
    elif d.validation.get("negation"):
        d.route, d.why = REFUSE, "request was negated"
    elif d.confidence >= act_threshold and any(c.get("name") in always_confirm for c in d.calls):
        d.route, d.why = CONFIRM, "this action always asks first"
    elif d.confidence >= act_threshold:
        d.route, d.why = ACT, f"confidence {d.confidence:.2f} >= {act_threshold}"
    elif d.confidence >= confirm_threshold:
        d.route, d.why = CONFIRM, f"confidence {d.confidence:.2f} needs confirmation"
    else:
        d.route, d.why = REFUSE, f"confidence {d.confidence:.2f} < {confirm_threshold}"
    return d


class Registry:
    """Tool schemas for Needle + the executors we dispatch to after the gate.

    Descriptions and triggers were tuned on the real model (42 commands, 12
    nonsense phrases): triggers took the right tool from 31/42 to 41/42 and
    removed every wrong call with confidence >= 0.75. A system prompt made no
    difference and is not used.
    """

    ALWAYS_CONFIRM = {"cancel_reminder"}  # spec 8.3 spirit: confirm regardless of score

    def __init__(self, launcher, clock: Callable[[], dict], system=None, reminders=None,
                 files=None):
        import needle
        from needle import Field

        apps = Literal[tuple(launcher.names)]
        self.query = ""  # transcript of the utterance being dispatched
        T = needle.tool
        tools, ex = [], {}

        def add(fn, triggers, impl):
            tools.append(T(fn, triggers=triggers))
            ex[fn.__name__] = impl

        def get_time():
            "Say the current clock time. Only for questions asking what time it is."
        add(get_time, ["time", "clock"], lambda: clock())

        def open_app(name):
            "Launch an installed desktop application."
        open_app.__annotations__ = {"name": apps}
        add(open_app, ["open", "launch", "start"], launcher.open_app)

        if system is not None:
            def close_window(name):
                "Close an open application's window."
            close_window.__annotations__ = {"name": apps}
            add(close_window, ["close", "quit", "exit"], launcher.close_window)

            def focus_window(name):
                "Switch to an already open application's window."
            focus_window.__annotations__ = {"name": apps}
            add(focus_window, ["switch", "focus", "go to", "bring up"], launcher.focus_window)

            def set_volume(level: Annotated[int, Field(ge=0, le=100)]):
                """Set the system volume.

                Args:
                    level: volume percent from 0 (mute) to 100
                """
            add(set_volume, ["volume", "louder", "quieter", "mute"], system.set_volume)

            def lock_screen():
                "Lock the computer."
            add(lock_screen, ["lock"], system.lock_screen)

            def sleep_display():
                "Turn the monitor/screen/display off without locking."
            add(sleep_display, ["turn off the display", "turn the screen off", "screen off",
                                "monitor off", "sleep the monitor"], system.sleep_display)

        if reminders is not None:
            def set_reminder(text: str, when: str):
                """Create a reminder.

                Args:
                    text: what to be reminded about
                    when: the full time phrase exactly as spoken, keeping every word, e.g. "tomorrow at six", "in 20 minutes", "friday at 3pm"
                """
            add(set_reminder, ["remind me to", "remind me in", "set a reminder", "reminder for"],
                lambda text, when: reminders.set_reminder(text, when, self.query))

            def list_reminders():
                "List upcoming reminders."
            add(list_reminders, ["reminders", "what are my reminders"], reminders.list_reminders)

            def cancel_reminder(id: int):
                """Cancel a reminder by its number.

                Args:
                    id: the reminder number
                """
            add(cancel_reminder, ["cancel reminder", "delete reminder"], reminders.cancel_reminder)

        if files is not None:
            def find_file(query: str, limit: int = 10):
                """Search this computer for documents or files by name.

                Args:
                    query: words from the file name
                    limit: maximum results
                """
            add(find_file, ["find my", "find the", "search for", "where is", "look for",
                            "find file"], files.find_file)

            def open_file(number: int):
                """Open a file from the numbered results of the last file search.

                Args:
                    number: the result number from the last search, starting at 1
                """
            add(open_file, ["open result", "open number", "open the first one",
                            "open the second one", "open the third one"], files.open_file)

        self.tools = tools
        self.executors: dict[str, Callable] = ex
        self.reminders = reminders

    @property
    def schemas(self) -> list[dict]:
        return [t._needle_tool for t in self.tools]

    def preview(self, call: dict) -> str:
        """Human-readable intent shown before confirmation (resolves reminder times)."""
        name, args = call.get("name"), call.get("arguments") or {}
        if name == "set_reminder" and self.reminders is not None:
            phrase, due = self.reminders.resolve(args.get("when", ""), self.query)
            from assistant.tools.reminders import fmt
            when = fmt(due) if due else f"'{phrase}' (not understood)"
            return f"remind you to '{args.get('text', '')}' on {when}"
        if name == "open_file":
            files = self.executors["open_file"].__self__
            n = args.get("number")
            try:
                return f"open {files.last_results[int(n) - 1]}"
            except Exception:
                return f"open result {n}"
        a = ", ".join(f"{k}={v!r}" for k, v in args.items())
        return f"{name}({a})"

    def dispatch(self, calls: list[dict], query: str = "") -> list[dict]:
        self.query = query
        results = []
        for call in calls:
            fn = self.executors.get(call.get("name"))
            if fn is None:
                results.append({"ok": False, "error": f"unknown tool {call.get('name')!r}"})
                continue
            try:
                results.append(fn(**(call.get("arguments") or {})))
            except TypeError as e:
                results.append({"ok": False, "error": f"bad arguments: {e}"})
            except Exception as e:  # executor bugs must not kill the listener
                results.append({"ok": False, "error": f"{type(e).__name__}: {e}"})
        return results


class IntentEngine:
    def __init__(self, registry: Registry, act_threshold: float, confirm_threshold: float,
                 confirm_floor: dict | None = None):
        import needle

        self.confirm_floor = dict(confirm_floor or {})
        self.registry = registry
        self.act_threshold = act_threshold
        self.confirm_threshold = confirm_threshold
        self.agent = needle.Needle(tools=registry.tools, stateless=True)

    @staticmethod
    def prepare(text: str) -> str:
        """Whistle ends sentences with '.', '?' or '!'. Measured: dropping only that
        final mark fixed e.g. 'Set the volume to 50.' (no tool, conf 0.00) -> set_volume
        (0.96). Case is kept: full lower-casing lowered confidence elsewhere."""
        return re.sub(r"[.!?…]+$", "", (text or "").strip()).strip()

    def decide(self, text: str) -> Decision:
        text = self.prepare(text)
        if not text:
            return gate(Decision(text, [], None), self.act_threshold, self.confirm_threshold)
        t0 = time.perf_counter()
        r = self.agent.complete(text, max_new_tokens=256)
        validation = r.get("validation") or {}
        calls = r.get("function_calls") or []
        if validation.get("ungrounded"):
            validation = dict(validation, ungrounded=self._reground(validation["ungrounded"],
                                                                    calls, text))
        d = Decision(
            query=text,
            calls=calls,
            confidence=r.get("confidence"),
            reasoning=r.get("reasoning") or "",
            suppressed=r.get("suppressed_calls") or [],
            validation=validation,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
        return gate(d, self.act_threshold, self.confirm_threshold,
                    self.registry.ALWAYS_CONFIRM, self.confirm_floor)

    @staticmethod
    def _reground(flags: list[str], calls: list[dict], text: str) -> list[str]:
        """Needle flags set_reminder.when as ungrounded when the model writes
        'one minute' as '1 minute'. `when` is re-resolved from the transcript by
        assistant.timeparse anyway, so for that one field we apply our own check
        (phrase present after number words -> digits) instead of the literal one.
        Every other flag is kept."""
        from assistant.timeparse import grounded_in
        keep = []
        for flag in flags:
            if flag == "set_reminder.when":
                whens = [c["arguments"].get("when", "") for c in calls
                         if c.get("name") == "set_reminder"]
                if whens and all(grounded_in(w, text) for w in whens):
                    continue
            keep.append(flag)
        return keep
