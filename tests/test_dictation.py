"""Executor tests: no real clipboard or keystrokes (spec 10)."""
from unittest import mock

from assistant.tools.dictation import paste_text


class FakeClipboard:
    def __init__(self, value):
        self.value = value
        self.history = []

    def paste(self):
        return self.value

    def copy(self, v):
        self.value = v
        self.history.append(v)


def _kb():
    kb = mock.MagicMock()
    kb.pressed.return_value.__enter__ = lambda *_: None
    kb.pressed.return_value.__exit__ = lambda *_: None
    return kb


def test_paste_sets_then_restores_clipboard():
    clip, kb = FakeClipboard("old contents"), _kb()
    assert paste_text("héllo, world — ✓", clipboard=clip, keyboard=kb,
                      paste_delay_ms=0, restore_delay_ms=0, keys=mock.MagicMock())
    assert clip.history == ["héllo, world — ✓", "old contents"]
    kb.press.assert_called_once_with("v")
    kb.release.assert_any_call("v")


def test_empty_transcript_does_nothing():
    clip, kb = FakeClipboard("old"), _kb()
    assert not paste_text("", clipboard=clip, keyboard=kb)
    assert clip.history == []
    kb.press.assert_not_called()


def test_no_per_character_typing():
    clip, kb = FakeClipboard(""), _kb()
    paste_text("a long sentence", clipboard=clip, keyboard=kb,
               paste_delay_ms=0, restore_delay_ms=0, keys=mock.MagicMock())
    kb.type.assert_not_called()
