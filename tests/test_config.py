import os

import assistant  # noqa: F401
from assistant import config


def test_config_loads_and_has_spec_keys():
    cfg = config.load()
    assert cfg["hotkeys"]["dictate"] == "ctrl+alt+d"
    assert cfg["speech"]["language"] == "en"
    assert 0 < cfg["intent"]["confirm_threshold"] < cfg["intent"]["act_threshold"] <= 1


def test_vocabulary_skips_comments():
    words = config.load_vocabulary(config.load())
    assert "Whistle" in words and not any(w.startswith("#") for w in words)


def test_telemetry_disabled():
    assert os.environ["NEEDLE_TELEMETRY"] == "0"
