"""Controllers that all emit the same four normalized flight controls."""

from __future__ import annotations

import json
import random
import shutil
import subprocess
from collections.abc import Mapping
from typing import Any, Protocol

from pydantic import BaseModel

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from .core import (
    TRIM_AILERON,
    TRIM_ELEVATOR,
    TRIM_RUDDER,
    ControlCommand,
    decision_timing,
)


class Controller(Protocol):
    def decide(self, observation: Mapping[str, Any] | BaseModel) -> ControlCommand: ...


def _neutral() -> ControlCommand:
    return ControlCommand(
        aileron=TRIM_AILERON,
        elevator=TRIM_ELEVATOR,
        rudder=TRIM_RUDDER,
        throttle=0.5,
    )


def _dict(value: Mapping[str, Any] | BaseModel) -> Mapping[str, Any]:
    return value.model_dump(mode="json") if isinstance(value, BaseModel) else value


def _clip(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return min(high, max(low, value))


class HumanController:
    """Returns the latest command supplied by the UI."""

    def __init__(self) -> None:
        self.command = _neutral()

    def set_command(self, command: ControlCommand) -> None:
        self.command = command

    def decide(self, observation: Mapping[str, Any] | BaseModel) -> ControlCommand:
        return self.command


class HoldController:
    def __init__(self, command: ControlCommand | None = None) -> None:
        self.command = command or _neutral()

    def decide(self, observation: Mapping[str, Any] | BaseModel) -> ControlCommand:
        return self.command


class RandomController:
    def __init__(self, seed: int = 42) -> None:
        self._random = random.Random(seed)

    def decide(self, observation: Mapping[str, Any] | BaseModel) -> ControlCommand:
        return ControlCommand(
            aileron=self._random.uniform(-1.0, 1.0),
            elevator=self._random.uniform(-1.0, 1.0),
            rudder=self._random.uniform(-1.0, 1.0),
            throttle=self._random.random(),
        )


class BaselineController:
    """Small proportional baseline, not an autopilot or a claimed safe lander.

    All corrections are additive to the trim offsets that keep the C172 in
    a stable approach at 65 KIAS / 20° flaps / 50 % throttle.
    """

    def decide(self, observation: Mapping[str, Any] | BaseModel) -> ControlCommand:
        state = _dict(observation)
        runway = state["runway"]
        flight = state["flight"]
        cmd = ControlCommand(
            aileron=_clip(
                TRIM_AILERON
                - 0.015 * runway.get("centerline_offset_m", runway["cross_track_error_m"])
                - 0.025 * runway["heading_error_deg"]
                - 0.08 * flight["roll_deg"]
                - 0.3 * flight.get("p_rad_s", 0.0)
            ),
            # JSBSim c172x positive elevator command is nose-down.
            elevator=_clip(
                TRIM_ELEVATOR
                + 0.10 * runway["glideslope_error_deg"]
                + 0.08 * (flight["vertical_speed_mps"] + 1.5)
                + 0.04 * (flight["pitch_deg"] - 3.0)
                - 0.2 * flight.get("q_rad_s", 0.0)
            ),
            rudder=_clip(
                TRIM_RUDDER
                + 0.03 * runway["heading_error_deg"]
                - 0.04 * flight["beta_deg"]
                - 0.15 * flight.get("r_rad_s", 0.0)
            ),
            throttle=_clip(0.5 + 0.05 * (30.0 - flight["airspeed_mps"]), 0.0, 1.0),
        )
        alt = runway.get("altitude_agl_m")
        if alt is not None and alt < 20.0:
            target_sink = -0.8
            current_vs = flight.get("vertical_speed_mps", -1.5)
            cmd = cmd.model_copy(
                update={
                    "elevator": _clip(-0.05 + 0.15 * (current_vs - target_sink)),
                    "throttle": _clip(cmd.throttle - 0.25, 0.0, 0.25),
                }
            )
        self.last_decision = {
            "controller": "baseline",
            "summary": f"X-track: {runway['cross_track_error_m']:.1f}m | GS: {runway['glideslope_error_deg']:.1f}° | VS: {flight['vertical_speed_mps']:.1f} m/s",
        }
        return cmd


def _import_llm() -> Any:
    try:
        import llm
    except ImportError as exc:
        raise RuntimeError(
            "Codex controller requires the 'codex' extra: "
            "uv sync --extra codex, then authenticate with 'codex login'."
        ) from exc
    return llm


def _codex_authenticated() -> bool:
    """Check the CLI session without reading or exposing cached credentials."""
    if not shutil.which("codex"):
        return False
    try:
        result = subprocess.run(
            ["codex", "login", "status"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0 and "chatgpt" in (result.stdout + result.stderr).lower()
    except (OSError, subprocess.TimeoutExpired):
        return False


def discover_models() -> list[str]:
    """Return installed Codex-subscription models without reading credentials."""
    if not _codex_authenticated():
        return []
    llm = _import_llm()
    return sorted(
        {model.model_id for model in llm.get_models() if model.model_id.startswith("openai-codex/")}
    )


class CodexController:
    def __init__(self, model: str | None = None) -> None:
        llm = _import_llm()
        available = discover_models()
        if not available:
            raise RuntimeError(
                "No authenticated openai-codex models found. Install the codex extra and run "
                "'codex login'; verify with 'codex login status'."
            )
        if model is None:
            model = available[0]
        if not model.startswith("openai-codex/"):
            raise ValueError("Codex model must start with 'openai-codex/'.")
        if model not in available:
            raise ValueError(f"Codex model is unavailable: {model}")
        self.model_id = model
        self._model = llm.get_model(model)
        self._previous = _neutral()

    def decide(self, observation: Mapping[str, Any] | BaseModel) -> ControlCommand:
        payload = {
            "observation": _dict(observation),
            "previous_action": self._previous.model_dump(),
        }
        response = self._model.prompt(
            json.dumps(payload, separators=(",", ":")),
            system=(
                "FlightBench evaluates a JSBSim C172 runway landing. Use only the supplied "
                "observation and previous_action to align with the runway and glidepath, "
                "reach a safe main-gear touchdown, and maintain the rollout. Return one JSON "
                "object containing exactly four absolute actuator commands: aileron, elevator, "
                "rudder in [-1,1] and throttle in [0,1]. These are target positions, not deltas; "
                "JSBSim computes the aircraft motion. Positive aileron banks right, positive "
                "elevator pitches nose down, and positive rudder yaws left. No prose or markdown."
            ),
            schema=ControlCommand,
            reasoning_effort="low",
        )
        self._previous = ControlCommand.model_validate_json(response.text())
        usage = (getattr(response, "response_json", None) or {}).get("usage")
        self.last_decision = {
            "controller": "codex",
            "model": self.model_id,
            "reasoning_effort": "low",
            "usage": usage,
            "input": payload,
            "command": self._previous.model_dump(),
        }
        return self._previous


JEV_MODEL = "jev-1.13.0"

JEV_COMMANDS = {
    "aileron": [-0.35, -0.25, -0.2, -0.15, -0.1, -0.05, 0.05],
    "elevator": [-0.3, -0.2, -0.1, -0.05, 0, 0.05, 0.1, 0.15, 0.2, 0.25],
    "rudder": [-0.1, 0, 0.05, 0.09, 0.13, 0.18, 0.28],
    "throttle": [0, 0.25, 0.4, 0.5, 0.65, 0.8, 1],
}

JEV_INSTRUCTIONS = {
    "aileron": "Choose the absolute aileron command using `flight.roll_deg` and `flight.p_rad_s` FIRST. Positive roll_deg means RIGHT bank; negative means LEFT bank. Positive p_rad_s means rolling RIGHT. Arrest a bank of 3 degrees or more BEFORE chasing runway alignment or sideways velocity; do not increase excessive bank. Only with bank below 3 degrees, first BRAKE sideways motion using motion.cross_track_rate_mps: above +0.5 m/s needs LEFT bank; below -0.5 m/s needs RIGHT bank, even if still on the opposite side of centerline. Wings level alone does NOT stop sideways drift. Only when sideways speed is below 0.5 m/s, use position to intercept: offset above +2m needs LEFT bank, below -2m needs RIGHT bank. Keep corrective bank small, about 2 degrees. Positive runway.centerline_offset_m means POSITION right of runway; positive runway.heading_error_deg means nose POINTING right, NOT position. Absolute trim aileron is -0.15; more positive rolls right, more negative rolls left.",
    "elevator": "Choose ABSOLUTE elevator during APPROACH. Positive commands pitch nose DOWN, negative nose UP. Follow the3-degree glidepath before threshold; normal sink1.5-3m/s is not an emergency. Modest nose-negative pitch can be normal while descending. Do not flare early. Use the matching approach criterion, considering vertical_speed_mps, pitch_deg and q_rad_s. Above glidepath and shallow descent needs more nose-down; arrest an actual worsening dive.",
    "rudder": "Select ABSOLUTE rudder command for C172 approach. Trim +0.09 counters propeller torque. Increasing yaw command turns nose LEFT; decreasing turns nose RIGHT. Positive heading error is pointing right of runway: increase rudder gently; negative heading error decrease. Damp yaw rate and beta sideslip. Near alignment use trim.",
    "throttle": "Select ABSOLUTE throttle for C172 approach. Aim approach airspeed 30 m/s; use about 0.5 at 30 m/s, add power if slow, reduce if fast. During FLARE reduce throttle to 0.25 or less during flare. Do not cut early while still high. Touchdown ideal airspeed 28m/s.",
}

JEV_CRITERIA = {
    "aileron": [
        "Strong LEFT roll correction: roll_deg above +8 (large RIGHT bank), especially p_rad_s positive. Recovery outranks runway offset.",
        "Moderate LEFT roll correction: roll_deg +3 to +8 degrees (RIGHT bank); reduce bank before it grows.",
        "Only with bank between -3 and +3 degrees: gentle LEFT roll, moving RIGHT faster than +0.5 m/s and roll>-2; OR nearly stationary sideways, position offset>+2m and roll>-2; OR centered with small RIGHT bank. NOT when moving LEFT faster than -0.5 m/s.",
        "Only with bank between -3 and +3 degrees: maintain current small bank: already banking LEFT about -2 degrees to brake RIGHT motion, or RIGHT about +2 degrees to brake LEFT motion; OR centered with sideways speed below 0.5 m/s and wings level.",
        "Only with bank between -3 and +3 degrees: gentle RIGHT roll, moving LEFT faster than -0.5 m/s and roll<+2; OR nearly stationary sideways, position offset<-2m and roll<+2; OR centered with small LEFT bank. NOT when moving RIGHT faster than +0.5 m/s.",
        "Moderate RIGHT roll correction: roll_deg -3 to -8 degrees (LEFT bank); reduce bank before it grows.",
        "Strong RIGHT roll correction: roll_deg below -8 (large LEFT bank), especially p_rad_s negative. Recovery outranks runway offset.",
    ],
    "elevator": [
        "Emergency nose-UP: severe dive sinking faster than8m/s, or pitch below -15 degrees and falling.",
        "Strong nose-UP: deep dive sinking6-8m/s, with pitch below -10 degrees.",
        "Firm nose-UP: dive sinking5-6m/s, with pitch below -7 degrees.",
        "Nose-UP recovery: sinking4.5-5m/s with nose below -5 and still falling.",
        "Nose-UP support: sinking4-4.5m/s with negative pitch.",
        "Moderate nose-UP support: sinking3.5-4m/s with negative pitch.",
        "Mild nose-UP support: below glidepath and descending, or sink3-3.5m/s worsening with nose low.",
        "Normal approach command: descent1-3m/s and modest pitch. Maintain normal descent; do not arrest it.",
        "Moderate nose-DOWN: before threshold, above glidepath by more than0.5 degrees and sink shallower than2m/s; OR climbing/pitch rising excessively.",
        "Strong nose-DOWN: steep climb faster than3m/s with pitch above10 degrees.",
    ],
    "rudder": [
        "Strong yaw RIGHT: nose points far LEFT of runway heading.",
        "Moderate yaw RIGHT: nose points LEFT of runway heading.",
        "Gentle yaw RIGHT: nose points slightly LEFT of runway heading.",
        "Trim yaw: nose aligned with runway and low yaw rate.",
        "Gentle yaw LEFT: nose points slightly RIGHT of runway heading.",
        "Moderate yaw LEFT: nose points RIGHT of runway heading.",
        "Strong yaw LEFT: nose points far RIGHT of runway heading.",
    ],
    "throttle": [
        "Idle for ground rollout or final flare with excessive airspeed.",
        "Reduced power during FLARE.",
        "Slightly reduced approach power for airspeed faster than 36 m/s; never when below glidepath.",
        "Normal approach power at airspeed 29 to 36 m/s, phase APPROACH; maintain while not safely in flare.",
        "Increased approach power for airspeed about 27 m/s.",
        "High approach power for airspeed about 24 m/s.",
        "Full power for dangerously low airspeed below 22 m/s.",
    ],
}


JEV_NEAR_GROUND_ELEVATOR = [
    "Strong nose-UP: sinking faster than3m/s, or imminent nose-first impact.",
    "Moderate nose-UP: sinking2-3m/s; arrest excessive flare sink.",
    "Nose-UP: sinking1.2-2m/s; reduce descent gently.",
    "Gentle support: sinking0.6-1.2m/s; maintain safe shallow descent.",
    "Light support: sinking0.3-0.6m/s; do not arrest descent entirely.",
    "Gentle nose-DOWN: descent nearly arrested or small climb, vertical speed -0.3 to +1m/s.",
    "Nose-DOWN: climbing1-2m/s.",
    "Moderate nose-DOWN: climbing2-3m/s.",
    "Firm nose-DOWN: climbing3-4m/s.",
    "Strong nose-DOWN: climbing above4m/s or pitch above10 and rising.",
]


class JevController:
    """One experimental Jev policy: four categorical decisions in one model request.

    Commands are absolute, not accumulated deltas. No baseline, confidence fallback,
    probability averaging or hidden stabilization. Flight performance is not guaranteed.
    """

    def __init__(
        self, model: str | None = None, api_key: str | None = None, decision_hz: int = 2
    ) -> None:
        from typesafe_sdk import Choice, RetryPolicy, TypeSafeClient

        if model not in (None, JEV_MODEL):
            raise ValueError(f"Jev uses one pinned model: {JEV_MODEL}")
        self._model = JEV_MODEL
        _, self._decision_interval_s = decision_timing(decision_hz)
        self._client = TypeSafeClient() if api_key is None else TypeSafeClient(api_key=api_key)
        self._retry = RetryPolicy(max_retries=0)
        self._questions = {
            axis: Choice(
                instructions=text
                + " Use current `flight` and `runway` state to choose one matching physical correction; do not select trim when the aircraft is diverging.",
                criteria={str(i): description for i, description in enumerate(JEV_CRITERIA[axis])},
            )
            for axis, text in JEV_INSTRUCTIONS.items()
        }
        self._near_ground_elevator = Choice(
            instructions="Choose ABSOLUTE elevator near ground (FLARE or ROLLOUT). More negative pitches nose UP, more positive nose DOWN. Choose by actual vertical speed; aim a modest nose-up attitude and controlled shallow descent, not a float or climb. On ground, allow the nose to settle gently.",
            criteria={str(i): text for i, text in enumerate(JEV_NEAR_GROUND_ELEVATOR)},
        )
        self.last_decision = None
        self.last_transition_details = None

    def decide(self, observation: Mapping[str, Any] | BaseModel) -> ControlCommand:
        obs = _dict(observation)
        state = {
            "flight": dict(obs["flight"]),
            "runway": dict(obs["runway"]),
            "current_controls": dict(obs.get("controls", {})),
            "time_s": obs.get("time_s", 0.0),
            "motion": dict(obs.get("temporal", {}).get("rates", {})),
            "status": dict(obs.get("status", {})),
            "phase": "ROLLOUT"
            if obs.get("status", {}).get("on_ground")
            else ("FLARE" if obs["runway"]["altitude_agl_m"] < 20 else "APPROACH"),
        }
        questions = dict(self._questions)
        if state["phase"] != "APPROACH":
            questions["elevator"] = self._near_ground_elevator
        response = self._client.system_one(
            state=state,
            questions=questions,
            model=self._model,
            retry=self._retry,
            timeout=10,
        )
        command = {}
        answers = {}
        for axis, values in JEV_COMMANDS.items():
            answer = response.choices.get(axis)
            choice = getattr(answer, "choice", None)
            if choice not in questions[axis].criteria:
                raise ValueError("Jev returned an invalid actuator choice")
            value = values[int(choice)]
            command[axis] = value
            answers[axis] = {
                "choice": choice,
                "label": questions[axis].criteria[choice],
                "command": value,
                "confidence": answer.confidence,
                "probabilities": dict(answer.probabilities),
            }
        action = ControlCommand(**command)
        self.last_transition_details = {
            "action_id": "/".join(answers[axis]["choice"] for axis in JEV_COMMANDS),
            "action_names": {axis: answers[axis]["label"] for axis in JEV_COMMANDS},
        }
        self.last_decision = {
            "controller": "jev",
            "model": self._model,
            "input": state,
            "policy": "direct-categorical",
            "experimental": True,
            "choices": answers,
            "command": action.model_dump(),
            "sdk_request": {
                "client_method": "system_one",
                "model": self._model,
                "questions": {
                    axis: {"type": "choice", "instructions": q.instructions, "criteria": q.criteria}
                    for axis, q in questions.items()
                },
            },
        }
        return action


def make_controller(
    name: str, seed: int | None = None, model: str | None = None, decision_hz: int = 2
) -> Controller:
    key = name.strip().lower()
    if key == "human":
        return HumanController()
    if key == "hold":
        return HoldController()
    if key == "random":
        return RandomController(seed)
    if key == "baseline":
        return BaselineController()
    if key == "codex":
        return CodexController(model)
    if key == "jev":
        return JevController(model=model, decision_hz=decision_hz)
    raise ValueError(
        f"Unknown controller {name!r}; choose human, hold, random, baseline, codex, or jev."
    )
