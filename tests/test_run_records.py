import json
import time
from datetime import UTC, datetime
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from flightbench import benchmark, runs, server
from flightbench.controllers import ControlCommand


def _record(run_id: str, *, variant: str = "81", status: str = "landed") -> dict:
    now = datetime.now(UTC).isoformat()
    return {
        "schema_version": 1,
        "run_id": run_id,
        "source": "cli",
        "started_at": now,
        "finished_at": now,
        "config": {
            "controller": "mock",
            "model": None,
            "scenario": "easy",
            "mode": "lockstep",
            "seed": 42,
            "action_variant": variant,
            "decision_hz": 2,
            "time_scale": 1.0,
            "stability_maintainer": False,
            "stability_threshold": 0.1,
            "delta_scale": 1.0,
            "human_assistance": {"auto_center": False, "wing_leveler": False},
        },
        "source_identity": {"versions": {}, "source_hash": "sha256:test"},
        "initial_observation": {},
        "final_state": {},
        "outcome": {
            "success": status == "landed",
            "quality": 75.0 if status == "landed" else 0.0,
            "status": status,
            "touchdown": None,
        },
        "diagnostics": {
            "decision_count": 1,
            "mean_latency_ms": 2.0,
            "calls": 1,
            "late_decisions": 0,
            "stale_decisions": 0,
            "api_errors": 0,
            "last_api_error": None,
        },
        "decisions": [],
    }


def test_json_store_round_trip_and_newest_first(tmp_path):
    first = _record("00000000-0000-4000-8000-000000000001")
    second = _record("00000000-0000-4000-8000-000000000002")
    first["finished_at"] = "2026-01-01T00:00:00+00:00"
    second["finished_at"] = "2026-01-02T00:00:00+00:00"

    runs.save_record(first, tmp_path)
    runs.save_record(second, tmp_path)

    assert runs.load_record(first["run_id"], tmp_path) == first
    assert [row["run_id"] for row in runs.list_records(tmp_path)] == [
        second["run_id"],
        first["run_id"],
    ]
    with pytest.raises(FileExistsError):
        runs.save_record(first, tmp_path)


def test_summary_keeps_comparable_settings_separate_and_counts_failures():
    one = _record("00000000-0000-4000-8000-000000000001", variant="81")
    two = _record("00000000-0000-4000-8000-000000000002", variant="micro", status="off_runway")
    provider_error = _record(
        "00000000-0000-4000-8000-000000000003", variant="micro", status="controller_error"
    )

    summary = benchmark.summarize([one, two, provider_error])

    assert len(summary) == 2
    failed = next(row for row in summary if row["action_variant"] == "micro")
    assert failed["failure_counts"] == {"off_runway": 1}
    assert failed["incomplete_counts"] == {"controller_error": 1}


def test_runs_api_and_tunnel_origins_are_local_only(monkeypatch, tmp_path):
    record = _record("00000000-0000-4000-8000-000000000001")
    runs.save_record(record, tmp_path)
    monkeypatch.setattr(server, "RUNS_DIR", tmp_path)
    client = TestClient(server.app, base_url="http://localhost")

    assert client.get("/api/runs").json()["runs"][0]["run_id"] == record["run_id"]
    assert client.get(f"/api/runs/{record['run_id']}").json() == record

    remote = TestClient(server.app, base_url="https://demo.trycloudflare.com")
    assert remote.get("/api/runs").status_code == 403
    with (
        pytest.raises(WebSocketDisconnect),
        remote.websocket_connect(
            "/ws",
            headers={"host": "demo.trycloudflare.com", "origin": "https://demo.trycloudflare.com"},
        ),
    ):
        pass


def test_cli_log_is_exclusive_and_record_has_shared_identity(monkeypatch, tmp_path):
    from tests.test_runner import FakeEnv, FixedController

    monkeypatch.setattr(benchmark, "FixedWingLandingEnv", FakeEnv)
    monkeypatch.setattr(benchmark, "make_controller", lambda *a, **k: FixedController())
    path = tmp_path / "episode.jsonl"

    record = benchmark.run_episode("mock", 7, log_path=path)

    assert record["run_id"]
    assert record["config"]["controller"] == "mock"
    assert record["source_identity"]["source_hash"].startswith("sha256:")
    with pytest.raises(FileExistsError):
        benchmark.run_episode("mock", 7, log_path=path)


def test_headless_report_selects_best_completed_run_and_prices_logged_usage(tmp_path):
    jev = _record("00000000-0000-4000-8000-000000000001")
    jev["config"].update(controller="jev", model="jev-1.13.0")
    jev["decisions"] = [
        {"decision_info": {"input": {"state": "test"}, "sdk_request": {"question": "hold"}}}
    ]
    codex = _record("00000000-0000-4000-8000-000000000002")
    codex["config"].update(controller="codex", model="openai-codex/gpt-6-luna", seed=101)
    codex["decisions"] = [
        {
            "decision_info": {
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "input_tokens_details": {"cached_tokens": 10, "cache_write_tokens": 5},
                }
            }
        }
    ]
    codex["diagnostics"]["calls"] = 1
    worse = json.loads(json.dumps(codex))
    worse["run_id"] = "00000000-0000-4000-8000-000000000003"
    worse["config"]["seed"] = 42
    worse["outcome"]["quality"] = 49
    interrupted = json.loads(json.dumps(codex))
    interrupted["outcome"]["status"] = "controller_error"
    interrupted["outcome"]["quality"] = 99

    rows = benchmark.report_rows([jev, worse, codex, interrupted])
    assert [r["controller"] for r in rows] == ["jev", "codex"]
    assert rows[1]["seed"] == 101
    assert rows[1]["cost_usd"] == pytest.approx(
        (85 * 0.1 + 10 * 0.01 + 5 * 0.125 + 20 * 0.5) / 1_000_000
    )
    assert "1.0×" in benchmark.report_markdown(rows)
    tie = json.loads(json.dumps(codex))
    tie["config"]["seed"] = 42
    assert benchmark.report_rows([codex, tie])[0]["seed"] == 42

    paths = []
    for index, record in enumerate((jev, codex)):
        path = tmp_path / f"{index}.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        paths.append(path)
    benchmark.main(
        ["--report-records", *(str(path) for path in paths), "--output-dir", str(tmp_path)]
    )
    report = next(tmp_path.glob("report-*.md")).read_text()
    assert "| Jev |" in report and "| GPT-6 Luna |" in report
    episodes = next(tmp_path.glob("episodes-*.md")).read_text()
    assert episodes.count("| GPT-6 Luna |") == 1
    assert codex["run_id"] in episodes
    assert not list(tmp_path.glob("summary-*.json"))


def test_headless_run_writes_markdown_beside_json_summary(monkeypatch, tmp_path):
    from tests.test_runner import FakeEnv, FixedController

    monkeypatch.setattr(benchmark, "FixedWingLandingEnv", FakeEnv)
    monkeypatch.setattr(benchmark, "make_controller", lambda *a, **k: FixedController())

    benchmark.main(["--controllers", "mock", "--seeds", "7", "--output-dir", str(tmp_path)])

    assert len(list(tmp_path.glob("summary-*.json"))) == 1
    report = next(tmp_path.glob("report-*.md")).read_text()
    assert "| mock | 7 | 75.000 | landed |" in report
    assert "Selected run IDs: mock" in report
    episodes = next(tmp_path.glob("episodes-*.md")).read_text()
    assert "| mock | 7 | 75.000 | landed |" in episodes


def test_episode_report_keeps_every_run_and_incomplete_logged_usage():
    completed = _record("00000000-0000-4000-8000-000000000001")
    completed["config"].update(controller="codex", model="openai-codex/gpt-6-sol", seed=101)
    completed["decisions"] = [
        {"decision_info": {"usage": {"input_tokens": 20, "output_tokens": 5}}}
    ]
    incomplete = json.loads(json.dumps(completed))
    incomplete["run_id"] = "00000000-0000-4000-8000-000000000002"
    incomplete["config"]["seed"] = 202
    incomplete["outcome"].update(status="controller_error", quality=0)
    incomplete["decisions"].append({"decision_info": {}})

    rows = benchmark.episode_rows([completed, incomplete])
    markdown = benchmark.episode_markdown(rows)

    assert [row["seed"] for row in rows] == [101, 202]
    assert rows[1]["missing_usage"] == 1
    assert rows[1]["cost_usd"] == pytest.approx(rows[0]["cost_usd"])
    assert markdown.count("| GPT-6 Sol |") == 2
    assert "| GPT-6 Sol | 202 | 0.000 | controller_error |" in markdown
    assert "≥$0.00009" in markdown


def test_source_hash_only_uses_known_files(monkeypatch, tmp_path):
    source = tmp_path / "flightbench.py"
    source.write_text("safe", encoding="utf-8")
    secret = tmp_path / ".env"
    secret.write_text("secret-one", encoding="utf-8")
    monkeypatch.setattr(runs, "SOURCE_FILES", (source,))

    before = runs.source_identity()["source_hash"]
    secret.write_text("secret-two", encoding="utf-8")

    assert runs.source_identity()["source_hash"] == before


def test_browser_lifecycle_persists_once_and_stop_does_not_restart(monkeypatch, tmp_path):
    from tests.test_runner import FakeEnv

    monkeypatch.setattr(server, "FixedWingLandingEnv", FakeEnv)
    monkeypatch.setattr(server, "RUNS_DIR", tmp_path)
    client = TestClient(server.app, base_url="http://localhost")

    with client.websocket_connect("/ws", headers={"host": "localhost"}) as websocket:
        websocket.send_json({"type": "start", "controller": "human", "mode": "realtime"})
        started = websocket.receive_json()
        assert started["type"] == "run_started"
        assert websocket.receive_json()["run_id"] == started["run_id"]
        while (message := websocket.receive_json())["type"] != "run_finished":
            pass
        assert message["record"]["outcome"]["status"] == "landed"
        websocket.send_json({"type": "stop"})
        assert websocket.receive_json() == {"type": "idle"}

    assert len(list(tmp_path.glob("*.json"))) == 1
    assert FakeEnv.instances[-1].done


def test_invalid_second_start_does_not_cancel_active_run(monkeypatch, tmp_path):
    class OngoingEnv:
        def __init__(self, **_kwargs):
            self.done = False
            self.decision_interval_s = 0.5
            self.decision_ticks = 60
            self.time_s = 0.0

        def reset(self, seed=42):
            return {"time_s": 0.0, "seed": seed, "controls": {}}, {}

        def advance(self, action, ticks=1):
            self.time_s += ticks / 120
            return {"time_s": self.time_s, "controls": action.model_dump()}, 0, False, False, {}

        def snapshot(self):
            return {"type": "state", "status": "running", "result": {"reason": "running"}}

    monkeypatch.setattr(server, "FixedWingLandingEnv", OngoingEnv)
    monkeypatch.setattr(server, "RUNS_DIR", tmp_path)
    client = TestClient(server.app, base_url="http://localhost")

    with client.websocket_connect("/ws", headers={"host": "localhost"}) as websocket:
        websocket.send_json({"type": "start", "controller": "human", "mode": "realtime"})
        run_id = websocket.receive_json()["run_id"]
        websocket.receive_json()
        websocket.send_json({"type": "start", "controller": "human", "mode": "invalid"})
        while (message := websocket.receive_json()).get("type") != "error":
            assert message.get("run_id") == run_id
        websocket.send_json({"type": "reset"})
        while (message := websocket.receive_json()).get("type") != "run_finished":
            pass
        assert message["run_id"] == run_id
        assert message["record"]["outcome"]["status"] == "interrupted"
        assert websocket.receive_json() == {"type": "idle"}


def test_realtime_stale_limit_tracks_decision_interval(monkeypatch):
    class TimedEnv:
        instances: ClassVar[list] = []

        def __init__(self, **_kwargs):
            self.done = False
            self.time_s = 0.0
            self.decision_interval_s = 0.1
            self.decision_ticks = 12
            TimedEnv.instances.append(self)

        def reset(self, seed=42):
            return {"time_s": 0.0, "seed": seed, "controls": {}}, {}

        def advance(self, action, ticks=1):
            self.time_s += ticks / 120
            self.done = self.time_s >= 0.35
            return {"time_s": self.time_s, "controls": action.model_dump()}, 0, self.done, False, {}

        def snapshot(self):
            return {"result": {"success": False, "quality": 0, "reason": "timeout"}}

    class SlowController:
        def decide(self, _observation):
            time.sleep(0.25)
            return ControlCommand(aileron=0, elevator=0, rudder=0, throttle=0.5)

    monkeypatch.setattr(benchmark, "FixedWingLandingEnv", TimedEnv)
    monkeypatch.setattr(benchmark, "make_controller", lambda *a, **k: SlowController())

    record = benchmark.run_episode("mock", 42, mode="realtime", decision_hz=10)

    assert record["diagnostics"]["stale_decisions"] >= 1
    assert record["diagnostics"]["decision_count"] == 0
    assert record["diagnostics"]["calls"] >= 1
    stale = [d for d in record["decisions"] if d["discard_reason"] == "stale_observation"]
    assert all(not d["applied"] and d["control_before"] == d["control_after"] for d in stale)


@pytest.mark.parametrize("mode", ["lockstep", "realtime"])
def test_cli_controller_error_is_terminal_and_counts_no_applied_decision(monkeypatch, mode):
    class MultiStepEnv:
        def __init__(self, **_kwargs):
            self.done = False
            self.steps = 0
            self.decision_interval_s = 0.5
            self.decision_ticks = 60

        def reset(self, seed=42):
            return {"time_s": 0.0, "seed": seed, "controls": {}}, {}

        def step(self, action):
            self.steps += 1
            self.done = self.steps >= 3
            return (
                {"time_s": self.steps * 0.5, "controls": action.model_dump()},
                0,
                self.done,
                False,
                {},
            )

        def advance(self, action, ticks=1):
            self.steps += ticks
            self.done = self.steps >= 360
            return (
                {"time_s": self.steps / 120, "controls": action.model_dump()},
                0,
                self.done,
                False,
                {},
            )

        def snapshot(self):
            return {
                "status": "running",
                "result": {"success": False, "quality": 0, "reason": "running"},
            }

    class FailingController:
        calls = 0

        def decide(self, _observation):
            self.calls += 1
            raise RuntimeError("private-provider-error")

    controller = FailingController()
    monkeypatch.setattr(benchmark, "FixedWingLandingEnv", MultiStepEnv)
    monkeypatch.setattr(benchmark, "make_controller", lambda *a, **k: controller)

    record = benchmark.run_episode("mock", 42, mode=mode)

    assert controller.calls == 1
    assert record["outcome"]["status"] == "controller_error"
    assert record["diagnostics"]["decision_count"] == 0
    assert record["diagnostics"]["calls"] == 1
    assert record["diagnostics"]["api_errors"] == 1


@pytest.mark.parametrize("mode", ["lockstep", "realtime"])
def test_websocket_controller_error_finishes_after_one_call(monkeypatch, tmp_path, mode):
    class OngoingEnv:
        def __init__(self, **_kwargs):
            self.done = False
            self.decision_interval_s = 0.5
            self.decision_ticks = 60
            self.time_s = 0.0

        def reset(self, seed=42):
            return {"time_s": 0.0, "seed": seed, "controls": {}}, {}

        def step(self, action):
            return {"time_s": 0.5, "controls": action.model_dump()}, 0, False, False, {}

        def advance(self, action, ticks=1):
            self.time_s += ticks / 120
            return {"time_s": self.time_s, "controls": action.model_dump()}, 0, False, False, {}

        def snapshot(self):
            return {
                "type": "state",
                "status": "running",
                "result": {"success": False, "quality": 0, "reason": "running"},
            }

    class FailingController:
        calls = 0

        def decide(self, _observation):
            self.calls += 1
            raise RuntimeError("private-provider-error")

    controller = FailingController()
    monkeypatch.setattr(server, "FixedWingLandingEnv", OngoingEnv)
    monkeypatch.setattr(server, "make_controller", lambda *a, **k: controller)
    monkeypatch.setattr(server, "RUNS_DIR", tmp_path)
    client = TestClient(server.app, base_url="http://localhost")

    with client.websocket_connect("/ws", headers={"host": "localhost"}) as websocket:
        websocket.send_json({"type": "start", "controller": "mock", "mode": mode})
        finished = None
        error_message = None
        while finished is None:
            message = websocket.receive_json()
            if message.get("type") == "error":
                error_message = message["message"]
            if message.get("type") == "run_finished":
                finished = message

    assert controller.calls == 1
    assert (
        error_message
        == "Controller failed; the flight stopped and no new decisions will be requested."
    )
    assert finished["record"]["outcome"]["status"] == "controller_error"
    assert finished["record"]["diagnostics"]["decision_count"] == 0
    assert finished["record"]["diagnostics"]["calls"] == 1
    assert finished["record"]["diagnostics"]["api_errors"] == 1


def test_codex_has_longer_websocket_decision_deadline(monkeypatch):
    import asyncio

    monkeypatch.setattr(server, "CONTROLLER_TIMEOUT_S", 0.005)
    monkeypatch.setattr(server, "CODEX_CONTROLLER_TIMEOUT_S", 0.25)

    class SlowController:
        def decide(self, _observation):
            time.sleep(0.05)
            return ControlCommand(aileron=0, elevator=0, rudder=0, throttle=0.5)

    class Env:
        decision_interval_s = 0.5

    for name, expected_error in (("baseline", "controller_timeout"), ("codex", None)):
        session = server.Session(None, env=Env(), controller_name=name, observation={"time_s": 0.0})
        command, _, error, _ = asyncio.run(session._decision(SlowController()))
        assert error == expected_error
        assert (command is not None) == (expected_error is None)


def test_failed_serialization_never_publishes_partial_record(tmp_path):
    record = _record(runs.new_run_id())
    record["decisions"] = [object()]
    with pytest.raises(TypeError):
        runs.save_record(record, tmp_path)
    assert list(tmp_path.glob("*.json")) == []


@pytest.mark.parametrize(
    "bad",
    [
        {"seed": -1},
        {"decision_hz": 7},
        {"human_assistance": "yes"},
        {"delta_scale": float("nan")},
        {"stability_maintainer": "false"},
    ],
)
def test_invalid_settings_rejected_before_acceptance(monkeypatch, tmp_path, bad):
    monkeypatch.setattr(server, "RUNS_DIR", tmp_path)
    client = TestClient(server.app, base_url="http://localhost")
    with client.websocket_connect("/ws", headers={"host": "localhost"}) as ws:
        ws.send_json({"type": "start", "controller": "human", "mode": "realtime", **bad})
        assert ws.receive_json()["type"] == "error"
    assert not list(tmp_path.glob("*.json"))


def test_unavailable_controller_is_not_an_accepted_run(monkeypatch, tmp_path):
    def unavailable(*args, **kwargs):
        raise RuntimeError("private-provider-error")

    monkeypatch.setattr(server, "make_controller", unavailable)
    monkeypatch.setattr(server, "RUNS_DIR", tmp_path)
    client = TestClient(server.app, base_url="http://localhost")
    with client.websocket_connect("/ws", headers={"host": "localhost"}) as ws:
        ws.send_json({"type": "start", "controller": "codex", "mode": "lockstep"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "private-provider-error" not in json.dumps(msg)
    assert not list(tmp_path.glob("*.json"))


def test_disconnect_saves_interrupted_without_touchdown(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "RUNS_DIR", tmp_path)
    client = TestClient(server.app, base_url="http://localhost")
    with client.websocket_connect("/ws", headers={"host": "localhost"}) as ws:
        ws.send_json({"type": "start", "controller": "human", "mode": "realtime"})
        run_id = ws.receive_json()["run_id"]
        ws.receive_json()
    record = runs.load_record(run_id, tmp_path)
    assert record["outcome"]["status"] == "interrupted"
    assert record["outcome"]["touchdown"] is None
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_storage_failure_retains_original_outcome_for_retry(monkeypatch, tmp_path):
    import asyncio

    from tests.test_runner import FakeEnv

    messages = []

    class Socket:
        async def send_json(self, data):
            messages.append(data)

    session = server.Session(Socket(), env=FakeEnv())
    session.run_id = runs.new_run_id()
    session.env.done = True
    monkeypatch.setattr(server, "RUNS_DIR", tmp_path)

    def unavailable(*_args):
        raise OSError("disk full")

    monkeypatch.setattr(server, "save_record", unavailable)
    asyncio.run(session.finish())
    assert session.run_id is not None
    assert messages[-1]["code"] == "storage_error"
    monkeypatch.setattr(server, "save_record", runs.save_record)
    asyncio.run(session.stop())
    assert session.run_id is None
    assert messages[-1]["record"]["outcome"]["status"] == "landed"
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_send_side_disconnect_is_interruption(monkeypatch, tmp_path):
    import asyncio

    from starlette.websockets import WebSocketState

    from tests.test_runner import FakeEnv

    class ClosedSocket:
        application_state = WebSocketState.DISCONNECTED
        client_state = WebSocketState.DISCONNECTED

        async def send_json(self, _data):
            raise RuntimeError("Cannot call send once a close message has been sent.")

    session = server.Session(ClosedSocket(), env=FakeEnv())
    run_id = session.run_id = runs.new_run_id()
    monkeypatch.setattr(server, "RUNS_DIR", tmp_path)
    asyncio.run(session.run(session.state))
    assert runs.load_record(run_id, tmp_path)["outcome"]["status"] == "interrupted"
    assert session.run_id is None
