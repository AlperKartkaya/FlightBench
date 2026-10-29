import json

import pytest
from pydantic import ValidationError

from flightbench.loading import ExternalController
from flightbench.local import OllamaController
from flightbench.protocol import SharedActionDecision, protocol_metadata


def test_ollama_uses_shared_schema_and_rejects_invalid_output(monkeypatch):
    requests = []
    decision = {"aileron": "3", "elevator": "7", "rudder": "3", "throttle": "3"}

    def request(self, method, payload=None):
        requests.append((method, payload))
        if method == "show":
            return {"details": {"quantization_level": "Q4_K_M"}}
        if method == "tags":
            return {"models": [{"name": "test:1b", "digest": "sha256:test"}]}
        if method == "version":
            return {"version": "test"}
        return {
            "done": True,
            "message": {"content": json.dumps(decision)},
            "prompt_eval_count": 20,
            "eval_count": 10,
        }

    monkeypatch.setattr(OllamaController, "_request", request)
    controller = OllamaController("test:1b")
    observation = {"flight": {}, "runway": {"altitude_agl_m": 30}, "status": {}}
    assert controller.decide(observation).elevator == 0.15
    payload = requests[-1][1]
    assert payload["format"] == SharedActionDecision.model_json_schema()
    assert not payload["stream"] and not payload["think"]
    assert "Moderate LEFT roll correction" in payload["messages"][0]["content"]
    assert protocol_metadata().items() <= controller.last_decision.items()
    decision["throttle"] = "unknown"
    with pytest.raises(ValidationError):
        controller.decide(observation)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://localhost:1",
        "http://example.org",
        "http://localhost:1/path",
        "http://user:pw@localhost:1",
    ],
)
def test_ollama_is_local_only(endpoint):
    with pytest.raises(ValueError, match="loopback"):
        OllamaController("test:1b", endpoint)


def test_ollama_rejects_cloud_before_request():
    with pytest.raises(ValueError, match="cloud"):
        OllamaController("test:cloud")


def test_system_one_uses_identical_jev_questions(monkeypatch):
    from flightbench.protocol import action_space

    request_payload = {}
    truncated = False

    def request(self, method, payload=None):
        if method == "show":
            return {"capabilities": ["decision"]}
        if method == "tags":
            return {"models": [{"name": "nimble:test", "digest": "sha256:test"}]}
        if method == "version":
            return {"version": "0.35.0"}
        assert method == "systemone"
        request_payload.update(payload)
        return {
            "truncated": truncated,
            "answers": {
                axis: {"choice": "3", "probabilities": {"3": 1.0}}
                for axis in ("aileron", "elevator", "rudder", "throttle")
            },
            "usage": {"input_tokens": 40, "output_tokens": 4},
        }

    monkeypatch.setattr(OllamaController, "_request", request)
    controller = OllamaController("nimble:test")
    controller.decide({"flight": {}, "runway": {"altitude_agl_m": 10}})
    for axis, spec in action_space()["phases"]["FLARE"].items():
        assert request_payload["questions"][axis]["instructions"] == spec["instructions"]
        assert request_payload["questions"][axis]["criteria"] == {
            action["id"]: action["criterion"] for action in spec["actions"]
        }
    assert controller.last_decision["usage"]["output_tokens"] == 4
    truncated = True
    with pytest.raises(ValueError, match="truncated"):
        controller.decide({"flight": {}, "runway": {"altitude_agl_m": 10}})


def test_external_controller_loads_file_and_enforces_categorical_ai(tmp_path):
    path = tmp_path / "controller.py"
    path.write_text("""class Pilot:
    def decide(self, observation):
        assert set(observation) == {"flight", "runway", "current_controls", "time_s", "motion", "status", "phase"}
        return {"aileron":"3", "elevator":"7", "rudder":"3", "throttle":"3"}
""")
    controller = ExternalController(f"{path}:Pilot")
    observation = {"flight": {}, "runway": {}}
    assert controller.decide(observation).aileron == -0.15
    assert len(controller.metadata["adapter_sha256"]) == 64
    path.write_text("""class Pilot:
    def decide(self, observation):
        return {"aileron":-0.15, "elevator":0.17, "rudder":0.09, "throttle":0.5}
""")
    with pytest.raises(ValidationError):
        ExternalController(f"{path}:Pilot").decide(observation)


def test_new_records_have_protocol_and_model_metadata(monkeypatch):
    from flightbench import benchmark
    from tests.test_runner import FakeEnv, FixedController

    controller = FixedController()
    controller.model_id = "local-model"
    controller.metadata = {"controller_type": "ai", "model_digest": "sha256:test"}
    monkeypatch.setattr(benchmark, "FixedWingLandingEnv", FakeEnv)
    monkeypatch.setattr(benchmark, "make_controller", lambda *a, **k: controller)
    record = benchmark.run_episode("ollama", 42)
    assert protocol_metadata().items() <= record["config"].items()
    assert record["config"]["model"] == "local-model"
    assert record["config"]["protocol_participant"]
    assert record["source_identity"]["git_commit"]


def test_long_external_file_reference_evaluates_and_exports_both_modes(monkeypatch, tmp_path):
    from flightbench import benchmark
    from flightbench.environment import FixedWingLandingEnv
    from flightbench.leaderboard import validate_submission

    directory = tmp_path / ("nested-" * 20) / ("controller-" * 10)
    directory.mkdir(parents=True)
    path = directory / "pilot.py"
    path.write_text("""class Pilot:
    def decide(self, observation):
        return {"aileron":"3", "elevator":"7", "rudder":"3", "throttle":"3"}
""")
    reference = f"{path}:Pilot"
    assert len(reference) > 200
    monkeypatch.setattr(
        benchmark,
        "FixedWingLandingEnv",
        lambda **kw: FixedWingLandingEnv(**(kw | {"max_time_s": 0.025})),
    )
    output = tmp_path / "submission"
    benchmark.evaluate(
        [
            "--controller",
            reference,
            "--seeds",
            "42",
            "--modes",
            "lockstep,realtime",
            "--output-dir",
            str(output),
        ]
    )
    payload = json.loads((output / "submission.json").read_text())
    assert set(validate_submission(payload, output).results) == {"lockstep", "realtime"}
