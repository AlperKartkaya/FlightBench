import json
import time
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from flightbench import benchmark, server
from flightbench.controllers import ControlCommand
from flightbench.core import DECISION_TICKS


class FakeEnv:
    instances: ClassVar[list] = []

    def __init__(self, scenario="easy", max_time_s=120):
        self.scenario = scenario
        self.done = False
        self.calls = []
        self.ticks = 0
        FakeEnv.instances.append(self)

    def reset(self, seed=42):
        self.seed = seed
        return {"seed": seed, "controls": {}}, {}

    def step(self, action):
        return self.advance(action, DECISION_TICKS)

    def advance(self, action, ticks=1):
        self.calls.append((action.model_dump(), ticks))
        self.ticks += ticks
        self.done = self.ticks >= DECISION_TICKS
        return {"seed": self.seed, "controls": action.model_dump()}, 0, self.done, False, {}

    def snapshot(self):
        return {
            "type": "state",
            "status": "landed" if self.done else "running",
            "score": 75,
            "result": {
                "success": self.done,
                "quality": 75 if self.done else 0,
                "reason": "landed" if self.done else "running",
                "touchdown": {"sink_rate_mps": -1} if self.done else None,
            },
        }


class FixedController:
    def __init__(self, throttle=0.8, delay=0):
        self.throttle = throttle
        self.delay = delay

    def decide(self, observation):
        time.sleep(self.delay)
        return ControlCommand(aileron=0.1, elevator=0.2, rudder=0.3, throttle=self.throttle)


@pytest.fixture(autouse=True)
def fake_env(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "RUNS_DIR", tmp_path)
    FakeEnv.instances.clear()
    monkeypatch.setattr(benchmark, "FixedWingLandingEnv", FakeEnv)
    monkeypatch.setattr(server, "FixedWingLandingEnv", FakeEnv)
    monkeypatch.setattr(benchmark, "make_controller", lambda *a, **k: FixedController())
    monkeypatch.setattr(server, "make_controller", lambda *a, **k: FixedController())


def test_lockstep_episode_logs_sanitized_reproducible_record(tmp_path):
    path = tmp_path / "episode.jsonl"
    result = benchmark.run_episode("mock", 7, log_path=path)

    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert result["success"] is True
    assert result["quality"] == 75
    assert {key: rows[0][key] for key in ("type", "controller", "mode", "seed")} == {
        "type": "metadata",
        "controller": "mock",
        "mode": "lockstep",
        "seed": 7,
    }
    assert rows[0]["initial_observation"]["seed"] == 7
    assert "versions" in rows[0]
    assert rows[1]["action"]["throttle"] == 0.8
    assert rows[-1]["type"] == "episode"


def test_realtime_holds_previous_action_during_inference():
    benchmark.run_episode("mock", 1, mode="realtime")

    first_action, first_ticks = FakeEnv.instances[-1].calls[0]
    assert first_ticks == 1
    assert first_action["throttle"] == 0.5


def test_timeout_keeps_previous_controls_and_hides_provider_error(monkeypatch, tmp_path):
    monkeypatch.setattr(benchmark, "make_controller", lambda *a, **k: FixedController(delay=0.03))
    path = tmp_path / "timeout.jsonl"

    benchmark.run_episode("paid", 1, timeout_s=0.001, log_path=path)

    decision = json.loads(path.read_text().splitlines()[1])
    assert decision["error"] == "controller_timeout"
    assert decision["action"]["throttle"] == 0.5


def test_models_endpoint_and_remote_origin_rejection(monkeypatch):
    monkeypatch.setattr(server, "discover_models", lambda: ["openai-codex/test"])
    client = TestClient(server.app, base_url="http://localhost")
    assert client.get("/api/models").json() == {"models": ["openai-codex/test"]}

    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(
            "/ws", headers={"host": "localhost", "origin": "https://attacker.example"}
        ),
    ):
        pass


def test_human_websocket_uses_client_action():
    client = TestClient(server.app, base_url="http://localhost")
    with client.websocket_connect("/ws", headers={"host": "localhost"}) as websocket:
        websocket.send_json({"type": "start", "controller": "human", "mode": "realtime", "seed": 9})
        assert websocket.receive_json()["type"] == "run_started"
        assert websocket.receive_json()["type"] == "state"
        websocket.send_json(
            {
                "type": "action",
                "action": {"aileron": -0.1, "elevator": 0.2, "rudder": 0.0, "throttle": 0.7},
            }
        )
        final = websocket.receive_json()
        assert final["type"] == "state"
