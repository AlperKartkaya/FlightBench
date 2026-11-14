"""Live race lifecycle with real JSBSim and a fake provider; no paid requests."""

import asyncio
import time

import pytest

from flightbench import server
from flightbench.controllers import ControlCommand


class Socket:
    def __init__(self):
        self.messages = []

    async def send_json(self, message):
        self.messages.append(message)


class SlowJev:
    _model = "jev-1.13.0"

    def decide(self, observation):
        time.sleep(0.15)
        return ControlCommand(aileron=0, elevator=0, rudder=0, throttle=0.5)


def test_live_race_isolated_synchronized_and_stopped(monkeypatch, tmp_path):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-only")
    monkeypatch.setattr(server, "make_controller", lambda *a, **k: SlowJev())
    monkeypatch.setattr(server, "RUNS_DIR", tmp_path)

    async def check():
        socket = Socket()
        human = server.Session(socket)
        await human.start_race(
            {"type": "start_race", "controller": "human", "mode": "realtime", "seed": 42}
        )
        jev = human.opponent
        assert human.env is not jev.env
        assert human.initial_observation == jev.initial_observation
        assert human.race_start == jev.race_start
        assert human.start_gate is jev.start_gate and human.start_gate.is_set()
        original = jev.action
        human.action = ControlCommand(aileron=0.7, elevator=0, rudder=0, throttle=0.8)
        assert jev.action == original
        await asyncio.sleep(0.08)
        assert human.observation["time_s"] > 0.03
        assert jev.observation["time_s"] > 0.03
        assert jev.requests_completed == 0  # slow provider did not pause either simulator
        await human.stop("interrupted")
        assert human.task is None and jev.task is None
        assert human.run_id is None and jev.run_id is None
        calls = jev.requests_started
        await asyncio.sleep(0.2)
        assert jev.requests_started == calls
        assert any(
            m["type"] == "ghost" and m["message"]["type"] == "run_finished" for m in socket.messages
        )
        assert len(list(tmp_path.glob("*.json"))) == 2

    asyncio.run(check())


def test_missing_credentials_does_not_start_paid_opponent(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    async def check():
        socket = Socket()
        human = server.Session(socket)
        await human.start_race({"controller": "human", "mode": "realtime"})
        assert human.task is None and human.opponent is None
        assert socket.messages[-1]["code"] == "controller_unavailable"

    asyncio.run(check())


def test_opponent_failure_does_not_end_human(monkeypatch, tmp_path):
    class FailedJev(SlowJev):
        def decide(self, observation):
            raise RuntimeError("fixture failure")

    monkeypatch.setenv("TYPESAFE_API_KEY", "test-only")
    monkeypatch.setattr(server, "make_controller", lambda *a, **k: FailedJev())
    monkeypatch.setattr(server, "RUNS_DIR", tmp_path)

    async def check():
        human = server.Session(Socket())
        await human.start_race({"controller": "human", "mode": "realtime"})
        await asyncio.sleep(0.15)
        assert human.task is not None and not human.task.done()
        assert human.opponent.task is None
        await human.stop()

    asyncio.run(check())


@pytest.mark.parametrize("next_action", ["stop", "start", "start_race"])
def test_human_finish_keeps_jev_alive_until_explicit_stop(monkeypatch, tmp_path, next_action):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-only")
    monkeypatch.setattr(server, "make_controller", lambda *a, **k: SlowJev())
    monkeypatch.setattr(server, "RUNS_DIR", tmp_path)

    async def check():
        human = server.Session(Socket())
        await human.start_race({"controller": "human", "mode": "realtime"})
        # End only the primary run, as a terminal landing does.
        human.task.cancel()
        try:
            await human.task
        except asyncio.CancelledError:
            pass
        human.task = None
        await human.finish()
        before = human.opponent.observation["time_s"]
        await asyncio.sleep(0.08)
        assert human.run_id is None
        assert human.opponent.task is not None
        assert human.opponent.observation["time_s"] > before
        previous = human.opponent
        if next_action == "stop":
            await human.stop()
        else:
            await getattr(human, next_action)({"controller": "human", "mode": "realtime"})
        assert previous.task is None and previous.run_id is None
        await human.stop()

    asyncio.run(check())


def test_all_ai_race_has_isolated_models_and_shared_start(monkeypatch, tmp_path):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-only")
    monkeypatch.setattr(server, "make_controller", lambda *a, **k: SlowJev())
    monkeypatch.setattr(server, "RUNS_DIR", tmp_path)

    async def check():
        socket = Socket()
        primary = server.Session(socket)
        await primary.start_race(
            {
                "controller": "jev",
                "model": "jev-1.14.0",
                "mode": "realtime",
                "decision_schedule": "continuous",
                "scenario": "hard",
                "seed": 101,
                "opponents": ["baseline", "jev-1.13.0"],
            }
        )
        runners = [primary, *primary.opponents]
        assert [r.controller_name for r in runners] == ["jev", "baseline", "jev"]
        assert len({id(r.env) for r in runners}) == 3
        assert all(r.initial_observation == primary.initial_observation for r in runners)
        assert all(r.race_start == primary.race_start for r in runners)
        assert all(r.start_gate is primary.start_gate for r in runners)
        await asyncio.sleep(0.2)
        assert {m["opponent_id"] for m in socket.messages if m["type"] == "ghost"} == {
            "baseline",
            "jev-1.13.0",
        }
        await primary.stop()
        assert all(r.task is None and r.run_id is None for r in runners)
        assert len(list(tmp_path.glob("*.json"))) == 3

    asyncio.run(check())


def test_continuous_realtime_does_not_wait_for_nominal_cadence(monkeypatch, tmp_path):
    class FastJev(SlowJev):
        def decide(self, observation):
            time.sleep(0.02)
            return ControlCommand(aileron=0, elevator=0, rudder=0, throttle=0.5)

    monkeypatch.setenv("TYPESAFE_API_KEY", "test-only")
    monkeypatch.setattr(server, "make_controller", lambda *a, **k: FastJev())
    monkeypatch.setattr(server, "RUNS_DIR", tmp_path)

    async def check():
        runner = server.Session(Socket())
        await runner.start(
            {
                "controller": "jev",
                "mode": "realtime",
                "decision_hz": 2,
                "decision_schedule": "continuous",
            }
        )
        await asyncio.sleep(0.25)
        assert runner.effective_decision_count >= 3  # fixed 2Hz would still have just one
        assert runner.requests_started - runner.requests_completed <= 1
        await runner.state()
        status = runner.websocket.messages[-1]["decision_info"]["live_status"]
        assert status["effective_decision_hz"] > 2
        assert status["avg_latency_ms"] > 0
        await runner.stop()

    asyncio.run(check())


@pytest.mark.parametrize(
    "opponents", [None, [], ["baseline", "baseline"], ["unknown"], [{"model": "jev"}]]
)
def test_invalid_race_never_creates_a_runner(opponents):
    async def check():
        primary = server.Session(Socket())
        with pytest.raises(ValueError, match="invalid race opponents"):
            await primary.start_race({"controller": "baseline", "opponents": opponents})
        assert primary.env is None and not primary.opponents

    asyncio.run(check())
