"""Pipeline routing with a fake engine: confirm band, refusal, logging."""
from unittest import mock

from assistant.intent import Decision, gate
from assistant.pipeline import CommandPipeline

CALL = [{"name": "open_app", "arguments": {"name": "notepad"}}]


def make(conf, calls=CALL, confirm=False):
    eng = mock.Mock()
    eng.decide.side_effect = lambda q: gate(Decision(q, calls, conf), 0.75, 0.45)
    eng.registry.dispatch.return_value = [{"ok": True, "opened": "notepad"}]
    eng.registry.schemas = []
    eng.registry.preview.side_effect = lambda c: c["name"]
    log, notes = mock.Mock(), []
    p = CommandPipeline(eng, log, confirm=lambda d: confirm,
                        notify=lambda t, b: notes.append((t, b)))
    return p, eng, log, notes


def test_high_confidence_executes():
    p, eng, log, notes = make(0.9)
    row = p.handle("open notepad")
    eng.registry.dispatch.assert_called_once()
    assert row["executed"] and "Opened notepad" in notes[-1][1]
    log.write.assert_called_once()


def test_confirm_band_declined_does_nothing():
    p, eng, _, notes = make(0.6, confirm=False)
    row = p.handle("open notepad")
    eng.registry.dispatch.assert_not_called()
    assert row["route"] == "confirm" and row["confirmed"] is False
    assert notes[0][0] == "Confirm?" and notes[-1][0] == "Cancelled"


def test_confirm_band_accepted_executes():
    p, eng, _, _ = make(0.6, confirm=True)
    assert p.handle("open notepad")["executed"]


def test_low_confidence_and_empty_show_transcript_only():
    for conf, calls in [(0.2, CALL), (0.99, [])]:
        p, eng, log, notes = make(conf, calls)
        row = p.handle("blah")
        eng.registry.dispatch.assert_not_called()
        assert not row["executed"] and "'blah'" in notes[-1][1]
        log.write.assert_called_once()
