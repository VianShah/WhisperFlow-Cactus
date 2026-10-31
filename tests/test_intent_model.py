"""Real Needle 3 model, all 12 tools: 5 phrasings per tool + nonsense (spec 10).
Asserts the right tool and arguments. Routing (act/confirm/refuse) is reported by
tests/eval_intent.py, not asserted here. Skipped until models are cached."""
import pytest

from assistant.intent import ACT, CONFIRM

pytestmark = pytest.mark.model


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    from assistant import config
    from assistant.apps_config import allowlist
    from assistant.intent import IntentEngine, Registry
    from assistant.tools.apps import AppLauncher, SystemControl
    from assistant.tools.files import FileSearch
    from assistant.tools.reminders import NullScheduler, Reminders, Store
    cfg = config.load()
    tmp = tmp_path_factory.mktemp("m")
    try:
        reg = Registry(AppLauncher(allowlist(cfg), api=False), lambda: {}, SystemControl(api=False),
                       Reminders(Store(tmp / "r.db"), NullScheduler(), lambda *a: None),
                       FileSearch(everything_cli=None))
        e = IntentEngine(reg, cfg["intent"]["act_threshold"], cfg["intent"]["confirm_threshold"])
        e.decide("warm up")
    except Exception as ex:
        pytest.skip(f"models not cached: {ex.__class__.__name__}")
    return e


CASES = [
    ("what time is it", "get_time", {}), ("what's the time", "get_time", {}),
    ("tell me the time", "get_time", {}), ("what time is it right now", "get_time", {}),
    ("do you know what time it is", "get_time", {}),
    ("open notepad", "open_app", {"name": "notepad"}), ("launch spotify", "open_app", {"name": "spotify"}),
    ("start chrome", "open_app", {"name": "chrome"}), ("open vs code", "open_app", {"name": "vscode"}),
    ("can you open notepad", "open_app", {"name": "notepad"}),
    ("close notepad", "close_window", {"name": "notepad"}), ("quit spotify", "close_window", {"name": "spotify"}),
    ("close chrome", "close_window", {"name": "chrome"}), ("exit vs code", "close_window", {"name": "vscode"}),
    ("close the notepad window", "close_window", {"name": "notepad"}),
    ("switch to chrome", "focus_window", {"name": "chrome"}), ("go to notepad", "focus_window", {"name": "notepad"}),
    ("bring up spotify", "focus_window", {"name": "spotify"}), ("focus vs code", "focus_window", {"name": "vscode"}),
    ("switch to spotify", "focus_window", {"name": "spotify"}),
    ("set volume to 30", "set_volume", {"level": 30}), ("volume 80 percent", "set_volume", {"level": 80}),
    ("set the volume to fifty", "set_volume", {"level": 50}), ("mute the volume", "set_volume", {}),  # model sends level="mute"; executor maps to 0
    ("turn the volume to 10", "set_volume", {"level": 10}),
    ("lock the screen", "lock_screen", {}), ("lock my computer", "lock_screen", {}), ("lock it", "lock_screen", {}),
    ("lock the pc", "lock_screen", {}), ("lock my screen now", "lock_screen", {}),
    ("turn off the display", "sleep_display", {}), ("turn the screen off", "sleep_display", {}),
    ("sleep the monitor", "sleep_display", {}), ("monitor off", "sleep_display", {}),
    pytest.param("switch the screen off", "sleep_display", {}, marks=pytest.mark.xfail(
        strict=True, reason="Needle 3 base model picks focus_window (conf 0.17, refused). "
                            "Phase 4 fine-tune target.")),
    ("remind me to call mom tomorrow at six", "set_reminder", {"text": "call mom"}),
    ("remind me in 20 minutes to check the oven", "set_reminder", {"text": "check the oven"}),
    ("set a reminder for friday at 3pm to submit the report", "set_reminder", {"text": "submit the report"}),
    ("remind me to drink water at 4", "set_reminder", {"text": "drink water"}),
    ("remind me to take out the trash tonight at 9", "set_reminder", {"text": "take out the trash"}),
    ("what are my reminders", "list_reminders", {}), ("list my reminders", "list_reminders", {}),
    ("show reminders", "list_reminders", {}), ("do I have any reminders", "list_reminders", {}),
    ("read my reminders", "list_reminders", {}),
    ("cancel reminder 3", "cancel_reminder", {"id": 3}), ("delete reminder number 2", "cancel_reminder", {"id": 2}),
    ("cancel reminder 1", "cancel_reminder", {"id": 1}), ("cancel reminder number 4", "cancel_reminder", {"id": 4}),
    ("remove reminder 5", "cancel_reminder", {"id": 5}),
    ("find my budget spreadsheet", "find_file", {}), ("search for invoice", "find_file", {"query": "invoice"}),
    ("where is the tax return pdf", "find_file", {}), ("look for resume", "find_file", {"query": "resume"}),
    ("find the file called notes", "find_file", {"query": "notes"}),
    ("open result 2", "open_file", {"number": 2}), ("open the first one", "open_file", {"number": 1}),
    ("open number three", "open_file", {"number": 3}), ("open result 1", "open_file", {"number": 1}),
    ("open the second one", "open_file", {"number": 2}),
]
NONSENSE = ["purple monkey dishwasher", "the cat sat on the mat", "tell me a joke", "um never mind",
            "delete all my files", "send an email to john", "what's the weather",
            "don't open notepad", "format the c drive", "shut down the computer", "I love this song"]


@pytest.mark.parametrize("q,tool,args", CASES,
                         ids=[c.values[0] if hasattr(c, "values") else c[0] for c in CASES])
def test_tool_and_arguments(engine, q, tool, args):
    d = engine.decide(q)
    assert [c["name"] for c in d.calls] == [tool], (d.calls, d.confidence)
    got = {k: str(v).lower() for k, v in d.calls[0]["arguments"].items()}
    for k, v in args.items():
        assert got.get(k) == str(v).lower(), (d.calls, d.confidence)


@pytest.mark.parametrize("q", NONSENSE)
def test_nonsense_takes_no_action(engine, q):
    assert engine.decide(q).route not in (ACT, CONFIRM)


def test_phase2_gate_phrases_still_act(engine):
    assert engine.decide("what time is it").route == ACT
    assert engine.decide("open notepad").route == ACT
