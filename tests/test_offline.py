"""Spec 8.5: a full command cycle (audio -> Whistle -> Needle -> executor) opens
no outbound socket once models are cached."""
import socket
from pathlib import Path
from unittest import mock

import pytest

FIX = Path(__file__).parent / "fixtures"


def test_full_cycle_opens_no_socket(monkeypatch, tmp_path):
    from assistant import config
    from assistant.intent import IntentEngine, Registry
    from assistant.logbook import Logbook
    from assistant.pipeline import CommandPipeline
    from assistant.stt import SpeechToText
    from assistant.tools.apps import AppLauncher
    from assistant.tools.clock import get_time

    cfg = config.load()
    try:
        stt = SpeechToText("en", config.load_vocabulary(cfg))  # as the app does
        reg = Registry(AppLauncher({"notepad": "notepad.exe"}, popen=mock.Mock(),
                                   which=lambda e: "/bin/notepad"), get_time)
        engine = IntentEngine(reg, 0.75, 0.45)
        engine.decide("warm up")
    except Exception as e:
        pytest.skip(f"models not cached: {e.__class__.__name__}")

    attempts = []

    def guard(self, *a, **k):
        attempts.append(a)
        raise AssertionError(f"outbound socket attempted: {a}")
    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket.socket, "connect_ex", guard)
    monkeypatch.setattr(socket, "create_connection", guard)

    pipe = CommandPipeline(engine, Logbook(tmp_path / "log.jsonl"),
                           confirm=lambda d: True, notify=lambda *a: None)
    text = stt.transcribe(str(FIX / "command_open_notepad.wav")).text
    row = pipe.handle(text)
    import time; time.sleep(0.5)  # let any background thread (e.g. telemetry) fire
    assert attempts == []
    assert row["executed"] and row["answers"][0]["name"] == "open_app"
