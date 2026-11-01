"""Live race lifecycle with real JSBSim and a fake provider; no paid requests."""
import asyncio
import time

from flightbench import server
from flightbench.controllers import ControlCommand


class Socket:
    def __init__(self):
        self.messages = []

    async def send_json(self, message):
        self.messages.append(message)


class SlowJev:
    _model = 'jev-1.13.0'

    def decide(self, observation):
        time.sleep(0.15)
        return ControlCommand(aileron=0, elevator=0, rudder=0, throttle=0.5)


def test_live_race_isolated_synchronized_and_stopped(monkeypatch, tmp_path):
    monkeypatch.setenv('TYPESAFE_API_KEY', 'test-only')
    monkeypatch.setattr(server, 'make_controller', lambda *a, **k: SlowJev())
    monkeypatch.setattr(server, 'RUNS_DIR', tmp_path)

    async def check():
        socket = Socket()
        human = server.Session(socket)
        await human.start_race({'type': 'start_race', 'controller': 'human', 'mode': 'realtime', 'seed': 42})
        jev = human.opponent
        assert human.env is not jev.env
        assert human.initial_observation == jev.initial_observation
        assert human.race_start == jev.race_start
        assert human.start_gate is jev.start_gate and human.start_gate.is_set()
        original = jev.action
        human.action = ControlCommand(aileron=.7, elevator=0, rudder=0, throttle=.8)
        assert jev.action == original
        await asyncio.sleep(.08)
        assert human.observation['time_s'] > .03
        assert jev.observation['time_s'] > .03
        assert jev.requests_completed == 0  # slow provider did not pause either simulator
        await human.stop('interrupted')
        assert human.task is None and jev.task is None
        assert human.run_id is None and jev.run_id is None
        calls = jev.requests_started
        await asyncio.sleep(.2)
        assert jev.requests_started == calls
        assert any(m['type'] == 'ghost' and m['message']['type'] == 'run_finished' for m in socket.messages)
        assert len(list(tmp_path.glob('*.json'))) == 2
    asyncio.run(check())


def test_missing_credentials_does_not_start_paid_opponent(monkeypatch):
    monkeypatch.delenv('TYPESAFE_API_KEY', raising=False)
    async def check():
        socket = Socket()
        human = server.Session(socket)
        await human.start_race({'controller': 'human', 'mode': 'realtime'})
        assert human.task is None and human.opponent is None
        assert socket.messages[-1]['code'] == 'controller_unavailable'
    asyncio.run(check())


def test_opponent_failure_does_not_end_human(monkeypatch, tmp_path):
    class FailedJev(SlowJev):
        def decide(self, observation):
            raise RuntimeError('fixture failure')
    monkeypatch.setenv('TYPESAFE_API_KEY', 'test-only')
    monkeypatch.setattr(server, 'make_controller', lambda *a, **k: FailedJev())
    monkeypatch.setattr(server, 'RUNS_DIR', tmp_path)
    async def check():
        human = server.Session(Socket())
        await human.start_race({'controller': 'human', 'mode': 'realtime'})
        await asyncio.sleep(.15)
        assert human.task is not None and not human.task.done()
        assert human.opponent.task is None
        await human.stop()
    asyncio.run(check())
