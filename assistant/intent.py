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

import time
from dataclasses import dataclass, field
from typing import Callable, Literal

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


def gate(d: Decision, act_threshold: float, confirm_threshold: float) -> Decision:
    """Spec 8.1. Pure function; sets d.route and d.why."""
    if not d.calls:
        d.route, d.why = NONE, "model chose no tool"
    elif d.confidence is None:
        # Local fine-tunes drop the confidence head: never act without a score.
        d.route, d.why = REFUSE, "no confidence score (uncalibrated weights)"
    elif d.validation.get("ungrounded"):
        d.route, d.why = REFUSE, "ungrounded arguments: " + ", ".join(d.validation["ungrounded"])
    elif d.validation.get("negation"):
        d.route, d.why = REFUSE, "request was negated"
    elif d.confidence >= act_threshold:
        d.route, d.why = ACT, f"confidence {d.confidence:.2f} >= {act_threshold}"
    elif d.confidence >= confirm_threshold:
        d.route, d.why = CONFIRM, f"confidence {d.confidence:.2f} needs confirmation"
    else:
        d.route, d.why = REFUSE, f"confidence {d.confidence:.2f} < {confirm_threshold}"
    return d


class Registry:
    """Tool schemas for Needle + the executors we dispatch to after the gate."""

    def __init__(self, launcher, clock: Callable[[], dict]):
        import needle

        app_names = tuple(launcher.names)

        def get_time():
            "Say the current clock time. Only for questions asking what time it is."
            return clock()

        def open_app(name):
            "Launch an installed desktop application."
            return launcher.open_app(name)
        open_app.__annotations__ = {"name": Literal[app_names]}

        self.tools = [needle.tool(get_time), needle.tool(open_app)]
        self.executors: dict[str, Callable] = {"get_time": get_time, "open_app": open_app}

    @property
    def schemas(self) -> list[dict]:
        return [t._needle_tool for t in self.tools]

    def dispatch(self, calls: list[dict]) -> list[dict]:
        results = []
        for call in calls:
            fn = self.executors.get(call.get("name"))
            if fn is None:
                results.append({"ok": False, "error": f"unknown tool {call.get('name')!r}"})
                continue
            try:
                results.append(fn(**(call.get("arguments") or {})))
            except Exception as e:  # executor bugs must not kill the listener
                results.append({"ok": False, "error": f"{type(e).__name__}: {e}"})
        return results


class IntentEngine:
    def __init__(self, registry: Registry, act_threshold: float, confirm_threshold: float):
        import needle

        self.registry = registry
        self.act_threshold = act_threshold
        self.confirm_threshold = confirm_threshold
        self.agent = needle.Needle(tools=registry.tools, stateless=True)

    def decide(self, text: str) -> Decision:
        text = (text or "").strip()
        if not text:
            return gate(Decision(text, [], None), self.act_threshold, self.confirm_threshold)
        t0 = time.perf_counter()
        r = self.agent.complete(text, max_new_tokens=256)
        d = Decision(
            query=text,
            calls=r.get("function_calls") or [],
            confidence=r.get("confidence"),
            reasoning=r.get("reasoning") or "",
            suppressed=r.get("suppressed_calls") or [],
            validation=r.get("validation") or {},
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
        return gate(d, self.act_threshold, self.confirm_threshold)
