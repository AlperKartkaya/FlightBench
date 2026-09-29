"""Local FastAPI/WebSocket runner for FlightBench."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from starlette.websockets import WebSocketState

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from .controllers import ControlCommand, discover_models, make_controller
from .core import (
    PHYSICS_HZ,
    TRIM_AILERON,
    TRIM_ELEVATOR,
    TRIM_RUDDER,
)
from .decision_tracking import DecisionTracker
from .environment import FixedWingLandingEnv
from .runs import (
    RunSettings,
    effective_config,
    list_records,
    load_record,
    new_run_id,
    now,
    save_record,
    source_identity,
)
from .temporal import TelemetryHistory

STATE_EVERY_TICKS = 4
CONTROLLER_TIMEOUT_S = 10.0
CODEX_CONTROLLER_TIMEOUT_S = 30.0
logger = logging.getLogger(__name__)

app = FastAPI(title="FlightBench", docs_url="/docs")
RUNS_DIR = Path(
    os.environ.get("FLIGHTBENCH_RUNS_DIR", Path(__file__).resolve().parent.parent / "runs")
)


def _localhost_origin(origin: str | None, host: str | None = None) -> bool:
    if not origin:  # Native/CLI WebSocket clients do not send Origin.
        return True
    hostname = urlparse(origin).hostname
    if not hostname:
        return False
    if hostname in {"localhost", "127.0.0.1", "::1"}:
        return True
    if host:
        host_hostname = urlparse(f"//{host}").hostname
        if host_hostname in {"localhost", "127.0.0.1", "::1"} and hostname == host_hostname:
            return True
    return False


def _localhost_host(host: str | None) -> bool:
    if not host:
        return False
    hostname = urlparse(f"//{host}").hostname
    if not hostname:
        return False
    return hostname in {"localhost", "127.0.0.1", "::1"}


@app.middleware("http")
async def local_api_only(request: Request, call_next):
    if request.url.path.startswith("/api/") and (
        not _localhost_host(request.headers.get("host"))
        or not _localhost_origin(request.headers.get("origin"), request.headers.get("host"))
    ):
        return JSONResponse({"detail": "localhost origin required"}, status_code=403)
    return await call_next(request)


def _action(data: object) -> ControlCommand:
    if not isinstance(data, dict):
        raise TypeError("action must be an object")
    return ControlCommand.model_validate(data)


def _action_dict(action: ControlCommand) -> dict[str, float]:
    if hasattr(action, "model_dump"):
        return action.model_dump()
    return {
        name: float(getattr(action, name)) for name in ("aileron", "elevator", "rudder", "throttle")
    }


@app.get("/api/models")
def models() -> dict[str, list[str]]:
    try:
        return {"models": list(discover_models())}
    except RuntimeError:
        return {"models": []}


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/runs")
def run_history() -> dict[str, list[dict]]:
    return {"runs": list_records(RUNS_DIR)}


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str) -> dict:
    try:
        return load_record(run_id, RUNS_DIR)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc


@dataclass
class Session:
    websocket: WebSocket
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    task: asyncio.Task[None] | None = None
    env: FixedWingLandingEnv | None = None
    controller_name: str = "baseline"
    mode: str = "lockstep"
    seed: int = 42
    model: str | None = None
    scenario: str = "easy"
    action: ControlCommand = field(
        default_factory=lambda: ControlCommand(
            aileron=TRIM_AILERON,
            elevator=TRIM_ELEVATOR,
            rudder=TRIM_RUDDER,
            throttle=0.5,
        )
    )
    observation: dict | None = None
    decision_count: int = 0
    latency_ms: float | None = None
    decision_info: dict | None = None
    calls_count: int = 0
    late_decisions: int = 0
    stale_decisions: int = 0
    api_errors: int = 0
    total_latency_ms: float = 0.0
    avg_latency_ms: float = 0.0
    last_api_error: str | None = None
    is_deciding: bool = False
    telemetry_history: TelemetryHistory = field(default_factory=TelemetryHistory)
    decision_tracker: DecisionTracker = field(default_factory=DecisionTracker)
    last_decision_started_s: float = 0.0
    state_age_ms: float | None = None
    decision_hz: int = 2
    time_scale: float = 1.0
    effective_decision_count: int = 0
    controller: Any = None
    run_id: str | None = None
    started_at: str | None = None
    initial_observation: dict | None = None
    run_config: dict | None = None
    human_assistance: dict[str, bool] = field(
        default_factory=lambda: {"auto_center": False, "wing_leveler": False}
    )

    decisions: list[dict] = field(default_factory=list)
    identity: dict | None = None
    pending_record: dict | None = None

    async def send(self, message: dict) -> None:
        async with self.send_lock:
            try:
                await self.websocket.send_json(message)
            except RuntimeError as exc:
                if (
                    self.websocket.application_state == WebSocketState.DISCONNECTED
                    or self.websocket.client_state == WebSocketState.DISCONNECTED
                ):
                    raise WebSocketDisconnect() from exc
                raise

    async def state(self) -> None:
        assert self.env is not None
        state = self.env.snapshot()
        state["decision_count"] = self.decision_count
        state["latency_ms"] = self.latency_ms
        state["controller_name"] = self.controller_name
        state["mode"] = self.mode
        state["run_id"] = self.run_id

        temporal = self.telemetry_history.features(self.observation) if self.observation else {}
        state["temporal"] = temporal
        if self.observation and "observation" in state and isinstance(state["observation"], dict):
            state["observation"]["temporal"] = temporal

        live_status = {
            "is_deciding": self.is_deciding,
            "cadence_hz": self.decision_hz,
            "nominal_decision_hz": self.decision_hz,
            "effective_decision_hz": (
                round(self.effective_decision_count / self.observation["time_s"], 2)
                if self.observation and self.observation.get("time_s", 0) > 0
                else 0.0
            ),
            "simulation_speed": self.time_scale,
            "calls": self.calls_count,
            "latency_ms": round(self.latency_ms, 1) if self.latency_ms is not None else None,
            "avg_latency_ms": round(self.avg_latency_ms, 1) if self.calls_count > 0 else None,
            "late_decisions": self.late_decisions,
            "stale_decisions": self.stale_decisions,
            "api_errors": self.api_errors,
            "last_api_error": self.last_api_error,
            "state_age_ms": round(self.state_age_ms, 1) if self.state_age_ms is not None else None,
        }
        if self.decision_info is not None:
            self.decision_info["live_status"] = live_status
        else:
            self.decision_info = {"controller": self.controller_name, "live_status": live_status}

        state["decision_info"] = self.decision_info
        await self.send(state)

    async def error(self, code: str) -> None:
        messages = {
            "invalid_request": "Request is invalid; check the WebSocket message fields.",
            "controller_timeout": "Controller timed out; the flight stopped and no new decisions will be requested.",
            "controller_error": "Controller failed; the flight stopped and no new decisions will be requested.",
            "controller_unavailable": "Controller is unavailable; check local setup and authentication.",
            "storage_error": "Run could not be saved. Free disk space and use Stop & save to retry; do not close this tab.",
        }
        message = messages.get(code, code)
        await self.send({"type": "error", "code": code, "message": message})

    async def stop(self, reason: str = "interrupted", *, idle: bool = False) -> None:
        task = self.task
        if task and task is not asyncio.current_task():
            self.task.cancel()
            try:
                await task
            except (asyncio.CancelledError, WebSocketDisconnect):
                pass
            self.task = None
        if self.run_id:
            await self.finish(reason)
        self.controller = None
        if idle and not self.run_id:
            await self.send({"type": "idle"})

    async def finish(self, status: str | None = None) -> None:
        if not self.run_id or not self.env:
            return
        final_state = self.env.snapshot()
        result = final_state.get("result") or {}
        outcome = {
            "success": bool(result.get("success", False)),
            "quality": float(
                result.get("quality", result.get("score", final_state.get("score", 0))) or 0
            ),
            "status": status or result.get("reason", final_state.get("status", "unknown")),
            "touchdown": result.get("touchdown"),
        }
        if status in {"interrupted", "error", "controller_timeout", "controller_error"}:
            outcome.update(success=False, quality=0.0)
        interventions = {
            "fallback": sum(d["fallback"] and d["applied"] for d in self.decisions),
            "stability_hold": sum(d["stability_hold"] and d["applied"] for d in self.decisions),
            "applied": self.effective_decision_count,
        }
        record = {
            "schema_version": 1,
            "run_id": self.run_id,
            "source": "browser",
            "started_at": self.started_at,
            "finished_at": now(),
            "config": self.run_config,
            "source_identity": self.identity,
            "initial_observation": self.initial_observation,
            "final_state": final_state,
            "outcome": outcome,
            "diagnostics": {
                "decision_count": self.decision_count,
                "mean_latency_ms": self.avg_latency_ms,
                "calls": self.calls_count,
                "late_decisions": self.late_decisions,
                "stale_decisions": self.stale_decisions,
                "api_errors": self.api_errors,
                "last_api_error": self.last_api_error,
                "interventions": interventions,
                "duration_s": (self.observation or {}).get("time_s", 0.0),
            },
            "decisions": self.decisions,
        }
        record = self.pending_record or record
        self.pending_record = record
        try:
            save_record(record, RUNS_DIR)
        except (OSError, ValueError, TypeError):
            logger.error("Run could not be saved; retained in session for retry")
            try:
                await self.error("storage_error")
            except (RuntimeError, WebSocketDisconnect):
                pass
            return
        run_id = self.run_id
        self.run_id = None
        self.pending_record = None
        try:
            await self.send({"type": "run_finished", "run_id": run_id, "record": record})
        except (RuntimeError, WebSocketDisconnect):
            pass

    async def start(self, message: dict) -> None:
        if self.task and not self.task.done():
            raise ValueError("run already active")
        if self.run_id:
            raise ValueError("previous run has not been saved")
        settings = RunSettings.model_validate(
            {key: value for key, value in message.items() if key != "type"}
        )
        controller_name = settings.controller
        mode = settings.mode
        seed = settings.seed
        model = settings.model
        scenario = settings.scenario
        decision_hz = settings.decision_hz
        time_scale = settings.time_scale if mode == "realtime" else 1.0
        human_assistance = settings.human_assistance.model_dump()
        if controller_name == "human" and mode != "realtime":
            raise ValueError("human controller requires realtime mode")

        controller = None
        if controller_name != "human":
            try:
                controller = make_controller(
                    controller_name,
                    seed=seed,
                    model=model,
                    decision_hz=decision_hz,
                )
            except Exception:  # noqa: BLE001
                logger.warning("Controller initialization failed")
                await self.error("controller_unavailable")
                return

        self.controller_name = controller_name
        self.mode = mode
        self.seed = seed
        self.model = model
        self.scenario = scenario
        self.decision_hz = decision_hz
        self.time_scale = time_scale
        self.human_assistance = human_assistance
        self.controller = controller

        try:
            self.env = FixedWingLandingEnv(
                scenario=self.scenario, max_time_s=120, decision_hz=self.decision_hz
            )
        except TypeError:
            self.env = FixedWingLandingEnv(scenario=self.scenario, max_time_s=120)
        self.observation, _ = self.env.reset(seed=self.seed)
        self.initial_observation = deepcopy(self.observation)
        self.telemetry_history = TelemetryHistory()
        self.telemetry_history.add(self.observation)
        self.decision_tracker = DecisionTracker()
        self.action = ControlCommand(
            aileron=TRIM_AILERON,
            elevator=TRIM_ELEVATOR,
            rudder=TRIM_RUDDER,
            throttle=0.5,
        )
        self.decision_count = 0
        self.latency_ms = None
        self.decision_info = None
        self.calls_count = 0
        self.late_decisions = 0
        self.stale_decisions = 0
        self.api_errors = 0
        self.total_latency_ms = 0.0
        self.avg_latency_ms = 0.0
        self.last_api_error = None
        self.is_deciding = False
        self.state_age_ms = None
        self.effective_decision_count = 0
        self.run_id = new_run_id()
        self.started_at = now()
        self.run_config = effective_config(settings, controller)
        self.identity = source_identity()
        self.decisions = []
        self.pending_record = None
        await self.send({"type": "run_started", "run_id": self.run_id, "config": self.run_config})
        await self.state()
        target = self._lockstep if self.mode == "lockstep" else self._realtime
        self.task = asyncio.create_task(self.run(target), name=f"flightbench-{id(self)}")

    async def run(self, target) -> None:
        try:
            await target()
            await self.finish()
        except asyncio.CancelledError:
            raise
        except WebSocketDisconnect:
            await self.finish("interrupted")
        except Exception:  # noqa: BLE001 - preserve an auditable local terminal record
            logger.error("Flight run failed")
            await self.finish("error")
        finally:
            self.task = None

    async def _decision(
        self, controller
    ) -> tuple[ControlCommand | None, float, str | None, dict | None]:
        started = perf_counter()
        observation = deepcopy(self.observation)
        self.last_decision_started_s = float(observation.get("time_s", 0.0))
        observation["temporal"] = self.telemetry_history.features(observation)
        observation["timing"] = {
            "sim_time_s": observation.get("time_s", 0.0),
            "decision_interval_s": getattr(self.env, "decision_interval_s", 1 / self.decision_hz),
        }
        observation["decision_feedback"] = self.decision_tracker.build_feedback(
            observation, float(observation.get("time_s", 0.0))
        )
        timeout = (
            CODEX_CONTROLLER_TIMEOUT_S if self.controller_name == "codex" else CONTROLLER_TIMEOUT_S
        )
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(controller.decide, observation),
                timeout=timeout,
            )
            decision_info = getattr(controller, "last_decision", None)
            return result, (perf_counter() - started) * 1000, None, decision_info
        except TimeoutError:
            return None, timeout * 1000, "controller_timeout", None
        except Exception:  # noqa: BLE001 - provider failures are an external trust boundary
            logger.warning("Controller decision failed")
            return None, (perf_counter() - started) * 1000, "controller_error", None

    def record_decision(self, info: dict | None, error: str | None, applied: bool) -> None:
        choice = ((info or {}).get("choices") or {}).get("joint_action") or {}
        self.decisions.append(
            {
                "index": self.calls_count,
                "sim_time_s": (self.observation or {}).get("time_s", 0.0),
                "observation_sim_time_s": self.last_decision_started_s,
                "latency_ms": self.latency_ms,
                "state_age_ms": self.state_age_ms,
                "applied": applied,
                "error": error,
                "action": _action_dict(self.action),
                "fallback": bool((choice.get("fallback") or {}).get("active")),
                "stability_hold": bool((choice.get("stability_maintainer") or {}).get("triggered")),
                "decision_info": deepcopy(info),
            }
        )

    async def _lockstep(self) -> None:
        assert self.env is not None
        controller = self.controller
        assert controller is not None
        while not self.env.done:
            self.is_deciding = True
            await self.state()
            next_action, self.latency_ms, error, decision_info = await self._decision(controller)
            self.is_deciding = False
            self.state_age_ms = 0.0
            self.calls_count += 1
            if self.latency_ms is not None:
                self.total_latency_ms += self.latency_ms
                self.avg_latency_ms = self.total_latency_ms / self.calls_count
            if next_action is not None:
                # Record transition in tracker before updating self.action.
                transition = getattr(controller, "last_transition_details", None)
                if transition:
                    sim_time = float(self.observation.get("time_s", 0.0))
                    actual_ctrls = (
                        self.observation.get("controls", {})
                        if isinstance(self.observation, dict)
                        else {}
                    )
                    self.decision_tracker.record_application(
                        action_id=transition["action_id"],
                        action_names=transition["action_names"],
                        sim_time=sim_time,
                        control_before={
                            a: float(actual_ctrls.get(a, getattr(self.action, a)))
                            for a in ("aileron", "elevator", "rudder", "throttle")
                        },
                        control_after={
                            a: float(getattr(next_action, a))
                            for a in ("aileron", "elevator", "rudder", "throttle")
                        },
                        state_snapshot=self.observation,
                    )
                self.action = next_action
                self.decision_count += 1
                self.effective_decision_count += 1
                self.decision_info = decision_info
            self.record_decision(decision_info, error, next_action is not None)
            if error:
                self.api_errors += 1
                self.last_api_error = error
                await self.error(error)
                await self.finish(error)
                return
            self.observation, _, _, _, _ = self.env.step(self.action)
            self.telemetry_history.add(self.observation)
            await self.state()

    async def _realtime(self) -> None:
        assert self.env is not None
        controller = self.controller
        pending: asyncio.Task | None = None
        ticks = 0
        loop = asyncio.get_running_loop()
        deadline = loop.time()
        cadence_deadline_ms = (
            getattr(self.env, "decision_interval_s", 1 / self.decision_hz) / self.time_scale * 1000
        )
        try:
            while not self.env.done:
                if pending and pending.done():
                    next_action, self.latency_ms, error, decision_info = pending.result()
                    pending = None
                    self.is_deciding = False
                    self.state_age_ms = max(
                        0.0,
                        (float(self.observation.get("time_s", 0.0)) - self.last_decision_started_s)
                        * 1000,
                    )
                    stale = (
                        self.state_age_ms
                        > 2 * getattr(self.env, "decision_interval_s", 1 / self.decision_hz) * 1000
                    )
                    if decision_info is not None:
                        decision_info.setdefault("timing", {})["state_age_at_application_ms"] = (
                            round(self.state_age_ms, 1)
                        )
                        decision_info["timing"]["applied"] = not stale
                        if stale:
                            decision_info["timing"]["discard_reason"] = "stale_observation"
                    self.calls_count += 1
                    if self.latency_ms is not None:
                        self.total_latency_ms += self.latency_ms
                        self.avg_latency_ms = self.total_latency_ms / self.calls_count
                        if self.latency_ms > cadence_deadline_ms:
                            self.late_decisions += 1
                    if stale and next_action is not None:
                        self.stale_decisions += 1
                    if next_action is not None and not stale:
                        # Record transition in tracker before updating self.action.
                        transition = getattr(controller, "last_transition_details", None)
                        if transition:
                            applied_sim_time = float(self.observation.get("time_s", 0.0))
                            actual_ctrls = (
                                self.observation.get("controls", {})
                                if isinstance(self.observation, dict)
                                else {}
                            )
                            self.decision_tracker.record_application(
                                action_id=transition["action_id"],
                                action_names=transition["action_names"],
                                sim_time=applied_sim_time,
                                control_before={
                                    a: float(actual_ctrls.get(a, getattr(self.action, a)))
                                    for a in ("aileron", "elevator", "rudder", "throttle")
                                },
                                control_after={
                                    a: float(getattr(next_action, a))
                                    for a in ("aileron", "elevator", "rudder", "throttle")
                                },
                                state_snapshot=self.observation,
                            )
                        self.action = next_action
                        self.decision_count += 1
                        self.effective_decision_count += 1
                    if decision_info is not None:
                        self.decision_info = decision_info
                    self.record_decision(
                        decision_info, error, next_action is not None and not stale
                    )
                    if error:
                        self.api_errors += 1
                        self.last_api_error = error
                        await self.error(error)
                        await self.finish(error)
                        return
                if (
                    controller
                    and ticks % getattr(self.env, "decision_ticks", PHYSICS_HZ // self.decision_hz)
                    == 0
                    and pending is None
                ):
                    self.is_deciding = True
                    pending = asyncio.create_task(self._decision(controller))

                self.observation, _, _, _, _ = self.env.advance(self.action, ticks=1)
                self.telemetry_history.add(self.observation)
                ticks += 1
                if ticks % STATE_EVERY_TICKS == 0 or self.env.done:
                    await self.state()
                deadline += 1 / (PHYSICS_HZ * self.time_scale)
                await asyncio.sleep(max(0, deadline - loop.time()))
        finally:
            if pending:
                pending.cancel()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    host_hdr = websocket.headers.get("host")
    origin_hdr = websocket.headers.get("origin")
    if not _localhost_host(host_hdr) or not _localhost_origin(origin_hdr, host_hdr):
        await websocket.close(code=1008, reason="localhost origin required")
        return
    await websocket.accept()
    session = Session(websocket)
    try:
        while True:
            try:
                message = json.loads(await websocket.receive_text())
            except (json.JSONDecodeError, TypeError):
                await session.error("invalid_request")
                continue
            if not isinstance(message, dict):
                await session.error("invalid_request")
                continue
            kind = message.get("type")
            try:
                if kind == "start":
                    await session.start(message)
                elif kind == "reset" or kind == "stop":
                    await session.stop("interrupted", idle=True)
                elif kind == "action":
                    if (
                        session.controller_name == "human"
                        and session.mode == "realtime"
                        and session.task is not None
                    ):
                        session.action = _action(message.get("action"))
                elif kind == "config_update":
                    raise ValueError("send settings with the next start request")
                else:
                    raise ValueError("unknown message type")
            except (KeyError, TypeError, ValueError):
                await session.error("invalid_request")
    except WebSocketDisconnect:
        pass
    finally:
        await session.stop("interrupted")


_DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _DIST_DIR.exists():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(_DIST_DIR), html=True), name="static")
