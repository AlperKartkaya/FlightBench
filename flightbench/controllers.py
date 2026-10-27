"""Controllers that all emit the same four normalized flight controls."""

from __future__ import annotations

import json
import random
import shutil
import subprocess
from collections.abc import Mapping
from typing import Any, Literal, Protocol

from pydantic import BaseModel, create_model

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
from .protocol import (
    COMMANDS,
    CRITERIA,
    DECISION_SUFFIX,
    INSTRUCTIONS,
    NEAR_GROUND_ELEVATOR,
    NEAR_GROUND_ELEVATOR_INSTRUCTIONS,
    SharedActionDecision,
    build_llm_control_prompt,
    canonical_observation,
    command_from_action_ids,
    criteria_for_phase,
    protocol_metadata,
)

JEV_COMMANDS = COMMANDS
JEV_CRITERIA = CRITERIA
JEV_INSTRUCTIONS = INSTRUCTIONS
JEV_NEAR_GROUND_ELEVATOR = NEAR_GROUND_ELEVATOR


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
    reasoning_effort = "low"

    def __init__(self, model: str | None = None, *, reasoning_effort: str = "low") -> None:
        if reasoning_effort not in {"low", "medium", "high", "xhigh", "max"}:
            raise ValueError("Codex reasoning effort must be low, medium, high, xhigh, or max")
        self.reasoning_effort = reasoning_effort
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
        if reasoning_effort == "max":
            # Installed plugin predates literal max; preserve its other option validation.
            self._model.Options = create_model(
                "CodexMaxOptions",
                __base__=self._model.Options,
                reasoning_effort=(Literal["low", "medium", "high", "xhigh", "max"] | None, None),
            )

    def decide(self, observation: Mapping[str, Any] | BaseModel) -> ControlCommand:
        payload = canonical_observation(observation)
        response = self._model.prompt(
            json.dumps(payload, separators=(",", ":")),
            system=build_llm_control_prompt(payload["phase"]),
            schema=SharedActionDecision,
            reasoning_effort=self.reasoning_effort,
        )
        decision = SharedActionDecision.model_validate_json(response.text())
        action = command_from_action_ids(decision)
        ids = decision.model_dump()
        active = criteria_for_phase(payload["phase"])
        usage = (getattr(response, "response_json", None) or {}).get("usage")
        self.last_decision = {
            "controller": "codex",
            "model": self.model_id,
            "reasoning_effort": self.reasoning_effort,
            "usage": usage,
            "action_ids": ids,
            "input": payload,
            "policy": "direct-categorical",
            "choices": {
                axis: {
                    "choice": choice,
                    "label": active[axis][int(choice)],
                    "command": JEV_COMMANDS[axis][int(choice)],
                }
                for axis, choice in ids.items()
            },
            "command": action.model_dump(),
            **protocol_metadata(),
        }
        return action


JEV_MODEL = "jev-1.13.0"
JEV_MODELS = (JEV_MODEL, "jev-1.14.0")


class JevController:
    """One experimental Jev policy: four categorical decisions in one model request.

    Commands are absolute, not accumulated deltas. No baseline, confidence fallback,
    probability averaging or hidden stabilization. Flight performance is not guaranteed.
    """

    def __init__(
        self, model: str | None = None, api_key: str | None = None, decision_hz: int = 2
    ) -> None:
        from typesafe_sdk import Choice, RetryPolicy, TypeSafeClient

        if model is not None and model not in JEV_MODELS:
            raise ValueError(f"Jev requires a pinned model: {JEV_MODELS}")
        self._model = model or JEV_MODEL
        _, self._decision_interval_s = decision_timing(decision_hz)
        self._client = TypeSafeClient() if api_key is None else TypeSafeClient(api_key=api_key)
        self._retry = RetryPolicy(max_retries=0)
        self._questions = {
            axis: Choice(
                instructions=text + DECISION_SUFFIX,
                criteria={str(i): description for i, description in enumerate(JEV_CRITERIA[axis])},
            )
            for axis, text in JEV_INSTRUCTIONS.items()
        }
        self._near_ground_elevator = Choice(
            instructions=NEAR_GROUND_ELEVATOR_INSTRUCTIONS,
            criteria={str(i): text for i, text in enumerate(JEV_NEAR_GROUND_ELEVATOR)},
        )
        self.last_decision = None
        self.last_transition_details = None

    def decide(self, observation: Mapping[str, Any] | BaseModel) -> ControlCommand:
        state = canonical_observation(observation)
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
        resolved_model = getattr(response, "model", None)
        if resolved_model != self._model:
            raise ValueError("Jev response model does not match the requested pinned version")
        usage = getattr(response, "usage", None)
        raw_choices = {
            axis: getattr(answer, "choice", None) for axis, answer in response.choices.items()
        }
        try:
            decision = SharedActionDecision.model_validate(raw_choices)
        except ValueError as exc:
            raise ValueError("Jev returned an invalid actuator choice") from exc
        action = command_from_action_ids(decision)
        selected = decision.model_dump()
        answers = {}
        for axis in JEV_COMMANDS:
            answer = response.choices.get(axis)
            choice = selected[axis]
            value = JEV_COMMANDS[axis][int(choice)]
            answers[axis] = {
                "choice": choice,
                "label": questions[axis].criteria[choice],
                "command": value,
                "confidence": answer.confidence,
                "probabilities": dict(answer.probabilities),
            }
        self.last_transition_details = {
            "action_id": "/".join(answers[axis]["choice"] for axis in JEV_COMMANDS),
            "action_names": {axis: answers[axis]["label"] for axis in JEV_COMMANDS},
        }
        self.last_decision = {
            "controller": "jev",
            "model": self._model,
            "resolved_model": resolved_model,
            "usage": {
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
            },
            "action_ids": selected,
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
            **protocol_metadata(),
        }
        return action


def make_controller(
    name: str,
    seed: int | None = None,
    model: str | None = None,
    decision_hz: int = 2,
    reasoning_effort: str = "low",
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
        return CodexController(model, reasoning_effort=reasoning_effort)
    if key == "jev":
        return JevController(model=model, decision_hz=decision_hz)
    if key == "ollama":
        from .local import OllamaController

        return OllamaController(model=model)
    if key == "systemone":
        from .local import SystemOneController

        return SystemOneController(model=model)
    raise ValueError(
        f"Unknown controller {name!r}; choose human, hold, random, baseline, codex, jev, or ollama."
    )
