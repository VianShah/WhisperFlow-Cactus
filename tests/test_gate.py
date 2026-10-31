"""Spec 8.1 routing. Pure logic, no model."""
import pytest

from assistant.intent import ACT, CONFIRM, NONE, REFUSE, Decision, gate

CALL = [{"name": "open_app", "arguments": {"name": "notepad"}}]


def g(calls, conf, **kw):
    return gate(Decision("q", calls, conf, **kw), 0.75, 0.45).route


@pytest.mark.parametrize("conf,route", [
    (0.99, ACT), (0.75, ACT), (0.7499, CONFIRM), (0.45, CONFIRM), (0.4499, REFUSE), (0.0, REFUSE)])
def test_thresholds(conf, route):
    assert g(CALL, conf) == route


def test_empty_calls_never_act_even_at_high_confidence():
    assert g([], 0.99) == NONE


def test_missing_confidence_refuses():  # local fine-tunes drop the head
    assert g(CALL, None) == REFUSE


def test_ungrounded_and_negation_refuse():
    assert g(CALL, 0.99, validation={"ungrounded": ["open_app.name"]}) == REFUSE
    assert g(CALL, 0.99, validation={"negation": True}) == REFUSE
