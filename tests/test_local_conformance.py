"""Supported native overflow signals must not silently change the frozen input."""

import pytest

from flightbench.local import SystemOneController


@pytest.mark.parametrize(
    "signal",
    [
        {"truncated": True},
        {"usage": {"truncated": True}},
        {"usage": {"state_tokens": 101, "state_tokens_used": 100}},
        {
            "truncation": {
                "state_tokens": 101,
                "kept_tokens": 100,
                "strategy": "middle",
                "questions_affected": 4,
            }
        },
    ],
)
def test_native_truncation_is_refused(monkeypatch, signal):
    response = {
        "answers": {
            axis: {"choice": "3"} for axis in ("aileron", "elevator", "rudder", "throttle")
        },
        **signal,
    }
    monkeypatch.setattr(SystemOneController, "_request", lambda *a: response)
    controller = SystemOneController("test")
    with pytest.raises(ValueError, match="truncated"):
        controller.decide({"flight": {}, "runway": {"altitude_agl_m": 30}})
    assert not hasattr(controller, "last_decision")


def test_native_complete_input_preserves_context_audit(monkeypatch):
    response = {
        "answers": {
            axis: {"choice": "3"} for axis in ("aileron", "elevator", "rudder", "throttle")
        },
        "truncated": False,
        "truncation": None,
        "usage": {"state_tokens": 101, "state_tokens_used": 101, "input_tokens": 400},
    }
    monkeypatch.setattr(SystemOneController, "_request", lambda *a: response)
    controller = SystemOneController("test")
    controller.decide({"flight": {}, "runway": {"altitude_agl_m": 30}})
    assert controller.last_decision["input_integrity"] == {
        "truncated": False,
        "truncation": None,
    }
    assert controller.last_decision["usage"] == response["usage"]
