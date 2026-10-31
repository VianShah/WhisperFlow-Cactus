"""Cold-start seed set for fine-tuning, generated from phrasing templates.

This is NOT a substitute for your own reviewed log (the spec's dataset): it only
teaches the tool set's shape before real data exists. Phrases used by
tests/eval_intent.py are excluded so evaluation stays held-out.

    python tools/seed_examples.py > tools/seed_examples.jsonl
"""
from __future__ import annotations

import itertools
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

APPS = {"notepad": ["notepad", "note pad", "Notepad"], "chrome": ["chrome", "Chrome", "google chrome", "the browser"],
        "vscode": ["vs code", "VS Code", "visual studio code", "code"], "spotify": ["spotify", "Spotify"]}
POLITE = ["", "please ", "could you ", "can you ", "hey, "]
TAIL = ["", " please", " now", " for me"]


def C(tool, **args):
    return [{"name": tool, "arguments": args}]


def gen(rng):
    out = []
    add = lambda q, a: out.append({"query": q, "answers": a})
    for p, t in itertools.product(POLITE, TAIL):
        for q in ["what time is it", "what's the time", "tell me the time", "time check",
                  "what's the current time", "how late is it", "got the time"]:
            if rng.random() < .25:
                add(f"{p}{q}{t}".strip(), C("get_time"))
    for key, spoken in APPS.items():
        for s in spoken:
            for v in ["open", "launch", "start", "fire up", "run"]:
                add(f"{rng.choice(POLITE)}{v} {s}{rng.choice(TAIL)}".strip(), C("open_app", name=key))
            for v in ["close", "quit", "exit", "shut", "close down"]:
                add(f"{rng.choice(POLITE)}{v} {s}{rng.choice(TAIL)}".strip(), C("close_window", name=key))
            for v in ["switch to", "go to", "focus", "bring up", "show me", "jump to"]:
                add(f"{rng.choice(POLITE)}{v} {s}{rng.choice(TAIL)}".strip(), C("focus_window", name=key))
    words = {0: "zero", 10: "ten", 20: "twenty", 25: "twenty five", 40: "forty", 60: "sixty",
             70: "seventy", 75: "seventy five", 90: "ninety", 100: "a hundred"}
    for lvl in [0, 5, 10, 15, 20, 25, 35, 40, 45, 55, 60, 65, 70, 75, 85, 90, 95, 100]:
        n = words.get(lvl, str(lvl)) if rng.random() < .4 else str(lvl)
        for tpl in ["set volume to {n}", "volume {n}", "turn the volume to {n} percent",
                    "put the sound at {n}", "change volume to {n}%"]:
            if rng.random() < .5:
                add(f"{rng.choice(POLITE)}{tpl.format(n=n)}".strip(), C("set_volume", level=lvl))
    for q in ["mute", "mute the sound", "silence the volume", "volume off"]:
        add(q, C("set_volume", level=0))
    for q in ["max volume", "volume all the way up", "full volume"]:
        add(q, C("set_volume", level=100))
    for q in ["lock", "lock the computer", "lock the pc", "lock this machine", "lock up",
              "lock my laptop", "lock the workstation"]:
        add(f"{rng.choice(POLITE)}{q}".strip(), C("lock_screen"))
    for q in ["turn the monitor off", "switch off the display", "screen off", "display off",
              "turn off my screen", "blank the screen", "sleep the display", "power off the monitor"]:
        add(f"{rng.choice(POLITE)}{q}".strip(), C("sleep_display"))
    tasks = ["call the dentist", "pay rent", "water the plants", "send the invoice",
             "pick up the kids", "join the standup", "take my medicine", "book flights",
             "email Priya", "review the contract", "feed the cat", "stretch", "back up the laptop",
             "buy milk", "check on the build", "reply to Arjun", "submit timesheet"]
    whens = ["in 10 minutes", "in an hour", "in 2 hours", "in half an hour", "tomorrow at 9",
             "tomorrow at 9 am", "tonight at 8", "at 5 pm", "at 7:30", "on monday at 10",
             "friday at noon", "tomorrow morning", "this evening", "in 45 minutes",
             "next tuesday at 2 pm", "at 3", "in three days"]
    for task in tasks:
        for when in rng.sample(whens, 4):
            tpl = rng.choice(["remind me to {t} {w}", "remind me {w} to {t}",
                              "set a reminder to {t} {w}", "{w} remind me to {t}",
                              "create a reminder {w} to {t}"])
            add(tpl.format(t=task, w=when), C("set_reminder", text=task, when=when))
    for q in ["show my reminders", "list reminders", "what reminders do I have",
              "any reminders", "read out my reminders", "what am I being reminded about",
              "upcoming reminders"]:
        add(q, C("list_reminders"))
    for i in range(1, 13):
        n = str(i) if rng.random() < .6 else ["one", "two", "three", "four", "five", "six",
                                                "seven", "eight", "nine", "ten", "eleven", "twelve"][i - 1]
        for tpl in ["cancel reminder {n}", "delete reminder {n}", "remove reminder number {n}",
                    "cancel reminder number {n}", "get rid of reminder {n}"]:
            if rng.random() < .45:
                add(tpl.format(n=n), C("cancel_reminder", id=i))
    things = ["invoice", "budget", "tax return", "resume", "contract", "meeting notes",
              "passport scan", "presentation", "receipts", "lease agreement", "project plan",
              "photo of the whiteboard", "quarterly report", "bank statement"]
    for t in things:
        for tpl in rng.sample(["find {t}", "find my {t}", "search for {t}", "where is my {t}",
                               "look for the {t}", "locate the {t} file", "find the {t} document",
                               "search my files for {t}"], 4):
            add(tpl.format(t=t), C("find_file", query=t))
    ords = ["first", "second", "third", "fourth", "fifth"]
    for i in range(1, 8):
        for tpl in ["open result {n}", "open number {n}", "open file {n}", "open item {n}",
                    "open the {o} one", "open the {o} result"]:
            if "{o}" in tpl and i > 5:
                continue
            if rng.random() < .6:
                add(tpl.format(n=i, o=ords[min(i, 5) - 1]), C("open_file", number=i))
    for q in ["what's the weather", "play some music", "send a message to mom", "order a pizza",
              "how tall is everest", "tell me a story", "translate hello to french",
              "delete this file", "shut down", "restart the computer", "format the drive",
              "uninstall chrome", "open the pod bay doors", "open photoshop", "launch excel",
              "do not open notepad", "never mind", "cancel", "uh", "hmm okay", "thank you",
              "that's all", "who are you", "I'm hungry", "this song is great",
              "the meeting went well", "move my files to the desktop", "empty the recycle bin",
              "email the report to john", "set an alarm", "what's on my calendar",
              "turn on the lights", "call mom", "take a screenshot", "copy this",
              "rename the file", "close all windows", "log me out", "update windows",
              "connect to wifi"]:
        add(q, [])
    return out


def main():
    import test_intent_model as T
    held_out = {(c.values[0] if hasattr(c, "values") else c[0]).lower() for c in T.CASES}
    held_out |= {q.lower() for q in T.NONSENSE}
    rng = random.Random(7)
    seen, n = set(), 0
    for ex in gen(rng):
        q = ex["query"].strip()
        if q.lower() in held_out or q.lower() in seen:
            continue
        seen.add(q.lower())
        print(json.dumps({"query": q, "answers": ex["answers"]}))
        n += 1
    print(f"{n} seed examples", file=sys.stderr)


if __name__ == "__main__":
    main()
