"""Insert text into the focused app via the clipboard (spec 6, Phase 1 step 5).

Save clipboard -> set transcript -> Ctrl+V -> restore original after a delay.
Never per-character keystrokes: slow, and they mangle punctuation and unicode.
"""
from __future__ import annotations

import time


def paste_text(text: str, *, clipboard=None, keyboard=None,
               paste_delay_ms: int = 40, restore_delay_ms: int = 250,
               keys=None) -> bool:
    """Returns True if something was pasted. Dependencies are injectable for tests."""
    if not text:
        return False
    if clipboard is None:
        import pyperclip as clipboard
    if keyboard is None:
        from pynput.keyboard import Controller
        keyboard = Controller()
    if keys is None:
        from pynput.keyboard import Key as keys

    try:
        previous = clipboard.paste()
    except Exception:
        previous = None

    clipboard.copy(text)
    time.sleep(paste_delay_ms / 1000)
    # The user is still physically releasing Ctrl+Alt+D; make sure Alt is up so
    # the target app sees a clean Ctrl+V and not Ctrl+Alt+V.
    keyboard.release(keys.alt)
    keyboard.release(keys.alt_l)
    with keyboard.pressed(keys.ctrl):
        keyboard.press("v")
        keyboard.release("v")
    time.sleep(restore_delay_ms / 1000)
    if previous is not None:
        clipboard.copy(previous)
    return True
