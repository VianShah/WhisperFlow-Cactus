from unittest import mock

import pytest

pytest.importorskip("PIL")

from assistant.tray import STATES, Tray, render


class FakeIcon:
    def __init__(self, name, icon, title, menu):
        self.name, self.icon, self.title, self.menu = name, icon, title, menu
        self.stopped = False
    def run(self): pass
    def stop(self): self.stopped = True


def make(**kw):
    quit_cb = mock.Mock()
    t = Tray(on_quit=quit_cb, data_dir="/tmp", icon_factory=FakeIcon, **kw)
    t._icon = FakeIcon("x", None, "", None)
    return t, quit_cb


def test_every_state_renders_distinct_colour():
    colours = {render(s).getpixel((32, 10)) for s in STATES}
    assert len(colours) == len(STATES)


def test_state_updates_icon_and_tooltip():
    t, _ = make()
    t.set_state("command")
    assert t._icon.title.endswith("- listening (command)")
    assert t._icon.icon.getpixel((32, 10))[:3] == STATES["command"][0]


def test_pause_overrides_other_states_until_resumed():
    t, _ = make()
    t.toggle_pause()
    t.set_state("dictate")
    assert t.state == "paused" and t.paused
    t.toggle_pause()
    assert t.state == "idle"


def test_quit_stops_icon_and_listener():
    t, quit_cb = make()
    t.quit()
    assert t._icon.stopped and quit_cb.called


def test_autostart_toggle():
    auto = mock.Mock()
    auto.is_enabled.return_value = False
    t, _ = make(autostart=auto)
    t.toggle_autostart()
    auto.enable.assert_called_once()
    auto.is_enabled.return_value = True
    t.toggle_autostart()
    auto.disable.assert_called_once()


def test_all_text_is_latin1_safe():
    """The X11 tray backend encodes titles as latin-1 ('—'/'…' crashed it)."""
    for _, label in STATES.values():
        ("Whistle Assistant - " + label).encode("latin-1")
