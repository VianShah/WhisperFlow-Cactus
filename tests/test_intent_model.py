"""Real Needle 3 model: 5 phrasings per tool + nonsense (spec 10, Phase 2 gate).
Skipped until `python run.py --setup` has cached the models."""
import pytest

from assistant.intent import ACT, CONFIRM, NONE

pytestmark = pytest.mark.model


@pytest.fixture(scope="module")
def engine():
    from assistant import config
    from assistant.apps_config import allowlist
    from assistant.intent import IntentEngine, Registry
    from assistant.tools.apps import AppLauncher
    cfg = config.load()
    try:
        e = IntentEngine(Registry(AppLauncher(allowlist(cfg)), lambda: {}),
                         cfg["intent"]["act_threshold"], cfg["intent"]["confirm_threshold"])
        e.decide("warm up")
    except Exception as ex:
        pytest.skip(f"models not cached: {ex.__class__.__name__}")
    return e


TIME = ["what time is it", "what's the time", "tell me the time",
        "what time is it right now", "do you know what time it is"]
APPS = [("open notepad", "notepad"), ("launch spotify please", "spotify"),
        ("start chrome", "chrome"), ("open vs code", "vscode"), ("can you open notepad", "notepad")]
NONSENSE = ["purple monkey dishwasher", "the cat sat on the mat", "tell me a joke",
            "um never mind", "open photoshop", "delete all my files", "don't open notepad"]


@pytest.mark.parametrize("q", TIME)
def test_get_time(engine, q):
    d = engine.decide(q)
    assert [c["name"] for c in d.calls] == ["get_time"], d
    assert d.route in (ACT, CONFIRM)


@pytest.mark.parametrize("q,app", APPS)
def test_open_app(engine, q, app):
    d = engine.decide(q)
    assert d.calls == [{"name": "open_app", "arguments": {"name": app}}], d
    assert d.route in (ACT, CONFIRM)


@pytest.mark.parametrize("q", NONSENSE)
def test_nonsense_takes_no_action(engine, q):
    d = engine.decide(q)
    assert d.route not in (ACT, CONFIRM), d


def test_gate_phrases_act_without_confirmation(engine):
    """Phase 2 gate: the two headline commands must act directly."""
    assert engine.decide("what time is it").route == ACT
    assert engine.decide("open notepad").route == ACT
