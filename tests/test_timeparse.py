from datetime import datetime

import pytest

from assistant.timeparse import expand_from_transcript, grounded_in, resolve

NOW = datetime(2026, 10, 31, 19, 50)  # Saturday evening


@pytest.mark.parametrize("phrase,expected", [
    ("in 20 minutes", "2026-10-31 20:10"),
    ("20 minutes", "2026-10-31 20:10"),
    ("in an hour", "2026-10-31 20:50"),
    ("in two hours", "2026-10-31 21:50"),
    ("in half an hour", "2026-10-31 20:20"),
    ("in 3 days", "2026-11-03 19:50"),
    ("tomorrow at six", "2026-11-01 18:00"),
    ("tomorrow at 6:30 pm", "2026-11-01 18:30"),
    ("tomorrow at 7", "2026-11-01 07:00"),
    ("tomorrow morning", "2026-11-01 09:00"),
    ("tomorrow at six in the morning", "2026-11-01 06:00"),
    ("friday at 3pm", "2026-11-06 15:00"),
    ("friday at 3 p.m.", "2026-11-06 15:00"),
    ("friday", "2026-11-06 09:00"),
    ("monday at noon", "2026-11-02 12:00"),
    ("at 4", "2026-11-01 16:00"),
    ("at 9", "2026-10-31 21:00"),
    ("at 7", "2026-11-01 07:00"),
    ("tonight at 9", "2026-10-31 21:00"),
    ("at 10 pm", "2026-10-31 22:00"),
    ("6 pm", "2026-11-01 18:00"),
    ("at noon", "2026-11-01 12:00"),
    ("half past five", "2026-11-01 17:30"),
    ("quarter to eight tomorrow", "2026-11-01 07:45"),
    ("at 8 30", "2026-10-31 20:30"),
    ("at 21:15", "2026-10-31 21:15"),
    ("saturday at 10 am", "2026-11-07 10:00"),
])
def test_resolve(phrase, expected):
    assert resolve(phrase, NOW).strftime("%Y-%m-%d %H:%M") == expected


@pytest.mark.parametrize("phrase", ["", "4", "banana", "yesterday at 3", "in 900 days", "whenever"])
def test_unresolvable_or_past_returns_none(phrase):
    assert resolve(phrase, NOW) is None


def test_expand_trimmed_phrase_from_transcript():
    assert expand_from_transcript("4", "remind me to drink water at 4") == "at 4"
    assert expand_from_transcript("friday", "set a reminder for friday at 3pm to submit the report") \
        == "friday at 3 pm"
    assert expand_from_transcript("20 minutes", "remind me in 20 minutes to check the oven") \
        == "in 20 minutes"
    assert expand_from_transcript("tomorrow at six", "remind me tomorrow at six") == "tomorrow at six"


def test_grounded_in_allows_digit_conversion_only():
    t = "Remind me in one minute to stretch"
    assert grounded_in("in 1 minute", t)
    assert grounded_in("in one minute", t)
    assert not grounded_in("in 10 minutes", t)
    assert not grounded_in("tomorrow", t)
    assert grounded_in("in 2 hours", "remind me in two hours to call mom")
