"""System tray icon (Phase 4.1): current mode at a glance, pause, autostart, quit.

Colour = state: grey idle, blue dictating, green command, amber thinking,
purple waiting for confirmation, red paused. The tooltip says the same in words.
pystray is imported lazily (on Linux it needs a display just to import), and the
icon factory is injectable so the state logic is testable without a desktop.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from typing import Callable

STATES = {
    "idle": ((128, 128, 128), "ready"),
    "dictate": ((33, 118, 230), "listening (dictation)"),
    "command": ((30, 160, 80), "listening (command)"),
    "thinking": ((230, 160, 20), "working..."),
    "confirm": ((140, 70, 200), "waiting for confirmation"),
    "paused": ((200, 50, 50), "paused (hotkeys off)"),
}


def render(state: str, size: int = 64):
    from PIL import Image, ImageDraw
    colour, _ = STATES[state]
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, size - 4, size - 4), fill=colour + (255,))
    # a simple microphone glyph so the icon reads as "voice"
    w = size // 8
    d.rounded_rectangle((size / 2 - w, size * .22, size / 2 + w, size * .58), radius=w,
                        fill=(255, 255, 255, 255))
    d.arc((size * .3, size * .36, size * .7, size * .68), 20, 160, fill=(255, 255, 255, 255),
          width=max(2, size // 20))
    d.line((size / 2, size * .68, size / 2, size * .78), fill=(255, 255, 255, 255),
           width=max(2, size // 20))
    return img


class Tray:
    def __init__(self, on_quit: Callable[[], None], data_dir: str,
                 autostart=None, icon_factory=None):
        self.state = "idle"
        self.paused = False
        self.on_quit = on_quit
        self.data_dir = data_dir
        self.autostart = autostart
        self._factory = icon_factory
        self._icon = None
        self._lock = threading.Lock()

    # -- state ---------------------------------------------------------------
    def set_state(self, state: str) -> None:
        if self.paused and state != "paused":
            state = "paused"
        with self._lock:
            self.state = state
            if self._icon is not None:
                self._icon.icon = render(state)
                self._icon.title = f"Whistle Assistant - {STATES[state][1]}"

    def toggle_pause(self, *_):
        self.paused = not self.paused
        self.set_state("paused" if self.paused else "idle")

    def toggle_autostart(self, *_):
        if self.autostart is None:
            return
        if self.autostart.is_enabled():
            self.autostart.disable()
        else:
            self.autostart.enable()

    def open_data(self, *_):
        if sys.platform == "win32":
            os.startfile(self.data_dir)
        else:
            subprocess.Popen(["xdg-open", self.data_dir], shell=False)

    def quit(self, *_):
        if self._icon is not None:
            self._icon.stop()
        self.on_quit()

    # -- pystray ----------------------------------------------------------------
    def _build(self):
        import pystray
        from pystray import Menu, MenuItem as Item
        items = [
            Item(lambda _: f"Whistle Assistant - {STATES[self.state][1]}", None, enabled=False),
            Menu.SEPARATOR,
            Item("Pause hotkeys", self.toggle_pause, checked=lambda _: self.paused),
        ]
        if self.autostart is not None:
            items.append(Item("Start with Windows", self.toggle_autostart,
                              checked=lambda _: self.autostart.is_enabled()))
        items += [Item("Open data folder", self.open_data), Menu.SEPARATOR,
                  Item("Quit", self.quit)]
        factory = self._factory or pystray.Icon
        return factory("whistle-assistant", render(self.state),
                       f"Whistle Assistant - {STATES[self.state][1]}", Menu(*items))

    def run(self) -> None:
        """Blocks until Quit. Call from the main thread (required on macOS, safest on Windows)."""
        self._icon = self._build()
        self._icon.run()
