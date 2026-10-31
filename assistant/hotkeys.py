"""Global push-to-talk hotkeys via pynput (no elevation needed on Windows).

Press the full chord -> on_press(mode). Release any key of the chord ->
on_release(mode). Key repeat while held is ignored.
"""
from __future__ import annotations

from typing import Callable


def _parse(chord: str):
    from pynput import keyboard
    keys = set()
    for part in chord.lower().split("+"):
        part = part.strip()
        if part in ("ctrl", "control"):
            keys.add("ctrl")
        elif part == "alt":
            keys.add("alt")
        elif part == "shift":
            keys.add("shift")
        elif part == "space":
            keys.add(keyboard.Key.space)
        elif len(part) == 1:
            keys.add(part)
        else:
            keys.add(getattr(keyboard.Key, part))
    return frozenset(keys)


class PushToTalk:
    def __init__(self, chords: dict[str, str],
                 on_press: Callable[[str], None],
                 on_release: Callable[[str], None]):
        self.chords = {mode: _parse(c) for mode, c in chords.items()}
        self.on_press = on_press
        self.on_release = on_release
        self._down: set = set()
        self._active: str | None = None
        self._listener = None

    def _normalise(self, key):
        from pynput import keyboard
        K = keyboard.Key
        if key in (K.ctrl, K.ctrl_l, K.ctrl_r):
            return "ctrl"
        if key in (K.alt, K.alt_l, K.alt_r, getattr(K, "alt_gr", None)):
            return "alt"
        if key in (K.shift, K.shift_l, K.shift_r):
            return "shift"
        if isinstance(key, keyboard.KeyCode):
            # With Ctrl held, Windows reports a control character; use the vk.
            if key.vk is not None and 0x41 <= key.vk <= 0x5A:
                return chr(key.vk).lower()
            if key.char:
                return key.char.lower()
        return key

    def _press(self, key):
        self._down.add(self._normalise(key))
        if self._active is None:
            for mode, chord in self.chords.items():
                if chord <= self._down:
                    self._active = mode
                    self.on_press(mode)
                    break

    def _release(self, key):
        k = self._normalise(key)
        self._down.discard(k)
        if self._active and k in self.chords[self._active]:
            mode, self._active = self._active, None
            self.on_release(mode)

    def run_forever(self):
        from pynput import keyboard
        with keyboard.Listener(on_press=self._press, on_release=self._release) as l:
            self._listener = l
            l.join()
