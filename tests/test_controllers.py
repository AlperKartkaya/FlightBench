import json
import sys
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from flightbench import controllers
from flightbench.controllers import (
    BaselineController,
    CodexController,
    ControlCommand,
    RandomController,
    discover_models,
    make_controller,
)
from flightbench.protocol import SharedActionDecision, canonical_observation, protocol_metadata

OBSERVATION = {
    "runway": {
        "cross_track_error_m": 4.0,
        "heading_error_deg": 2.0,
        "glideslope_error_deg": 0.5,
    },
    "flight": {
        "roll_deg": 1.0,
        "pitch_deg": 2.0,
        "vertical_speed_mps": -1.0,
        "beta_deg": 0.5,
        "airspeed_mps": 28.0,
    },
}


def test_control_command_is_strict_finite_and_bounded():
    command = ControlCommand(aileron=0, elevator=0, rudder=0, throttle=1)
    assert command.model_dump() == {
        "aileron": 0.0,
        "elevator": 0.0,
        "rudder": 0.0,
        "throttle": 1.0,
    }
    for invalid in (
        {"aileron": 1.1},
        {"elevator": float("nan")},
        {"rudder": float("inf")},
        {"throttle": -0.1},
        {"extra": 1},
    ):
        with pytest.raises(ValidationError):
            values = {"aileron": 0, "elevator": 0, "rudder": 0, "throttle": 0.5}
            ControlCommand(**(values | invalid))


def test_local_controllers_are_deterministic_and_factory_validates_name():
    first = RandomController(7).decide({})
    second = RandomController(7).decide({})
    assert first == second
    assert make_controller("hold").decide({}).throttle == 0.5
    assert isinstance(make_controller("baseline"), BaselineController)
    with pytest.raises(ValueError, match="Unknown controller"):
        make_controller("teleport")


def test_ollama_factory_lazily_passes_the_model(monkeypatch):
    created = SimpleNamespace()
    monkeypatch.setitem(
        sys.modules,
        "flightbench.local",
        SimpleNamespace(OllamaController=lambda model: setattr(created, "model", model) or created),
    )

    assert make_controller("ollama", model="local-model") is created
    assert created.model == "local-model"


def test_baseline_corrects_right_offset_and_low_airspeed():
    command = BaselineController().decide(OBSERVATION)
    assert command.aileron < 0
    assert command.rudder > 0
    assert command.throttle > 0.5


def test_codex_discovery_and_structured_decision(monkeypatch):
    request = {}
    response = SimpleNamespace(
        text=lambda: '{"aileron":"0","elevator":"4","rudder":"2","throttle":"5"}',
        response_json={"usage": {"input_tokens": 100, "output_tokens": 20}},
    )

    def prompt(*args, **kwargs):
        request.update(payload=args[0], **kwargs)
        return response

    fake_llm = SimpleNamespace(
        get_models=lambda: [
            SimpleNamespace(model_id="other/model"),
            SimpleNamespace(model_id="openai-codex/z"),
            SimpleNamespace(model_id="openai-codex/a"),
        ],
        get_model=lambda model: SimpleNamespace(prompt=prompt),
    )
    monkeypatch.setitem(sys.modules, "llm", fake_llm)
    monkeypatch.setattr(controllers, "_codex_authenticated", lambda: True)

    assert discover_models() == ["openai-codex/a", "openai-codex/z"]
    controller = CodexController()
    assert controller.model_id == "openai-codex/a"
    assert controller.decide(OBSERVATION).model_dump() == {
        "aileron": -0.35,
        "elevator": 0.0,
        "rudder": 0.05,
        "throttle": 0.8,
    }
    assert controller.last_decision["usage"] == {"input_tokens": 100, "output_tokens": 20}
    assert controller.last_decision["reasoning_effort"] == "low"
    assert request["schema"] is SharedActionDecision
    assert request["reasoning_effort"] == "low"
    assert all(axis in request["system"] for axis in ("aileron", "elevator", "rudder", "throttle"))
    assert "absolute" in request["system"] and "FlightBench" in request["system"]
    assert json.loads(request["payload"]) == canonical_observation(OBSERVATION)
    assert protocol_metadata().items() <= controller.last_decision.items()
