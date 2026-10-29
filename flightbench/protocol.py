"""Frozen provider-independent action space for official AI benchmarks."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .core import ControlCommand

BENCHMARK_PROTOCOL = "flightbench-v1"
ACTION_SPACE_VERSION = "flightbench-action-space-v1"
FLARE_ALTITUDE_AGL_M = 20.0

COMMANDS = {
    "aileron": [-0.35, -0.25, -0.2, -0.15, -0.1, -0.05, 0.05],
    "elevator": [-0.3, -0.2, -0.1, -0.05, 0, 0.05, 0.1, 0.15, 0.2, 0.25],
    "rudder": [-0.1, 0, 0.05, 0.09, 0.13, 0.18, 0.28],
    "throttle": [0, 0.25, 0.4, 0.5, 0.65, 0.8, 1],
}

INSTRUCTIONS = {
    "aileron": "Choose the absolute aileron command using `flight.roll_deg` and `flight.p_rad_s` FIRST. Positive roll_deg means RIGHT bank; negative means LEFT bank. Positive p_rad_s means rolling RIGHT. Arrest a bank of 3 degrees or more BEFORE chasing runway alignment or sideways velocity; do not increase excessive bank. Only with bank below 3 degrees, first BRAKE sideways motion using motion.cross_track_rate_mps: above +0.5 m/s needs LEFT bank; below -0.5 m/s needs RIGHT bank, even if still on the opposite side of centerline. Wings level alone does NOT stop sideways drift. Only when sideways speed is below 0.5 m/s, use position to intercept: offset above +2m needs LEFT bank, below -2m needs RIGHT bank. Keep corrective bank small, about 2 degrees. Positive runway.centerline_offset_m means POSITION right of runway; positive runway.heading_error_deg means nose POINTING right, NOT position. Absolute trim aileron is -0.15; more positive rolls right, more negative rolls left.",
    "elevator": "Choose ABSOLUTE elevator during APPROACH. Positive commands pitch nose DOWN, negative nose UP. Follow the3-degree glidepath before threshold; normal sink1.5-3m/s is not an emergency. Modest nose-negative pitch can be normal while descending. Do not flare early. Use the matching approach criterion, considering vertical_speed_mps, pitch_deg and q_rad_s. Above glidepath and shallow descent needs more nose-down; arrest an actual worsening dive.",
    "rudder": "Select ABSOLUTE rudder command for C172 approach. Trim +0.09 counters propeller torque. Increasing yaw command turns nose LEFT; decreasing turns nose RIGHT. Positive heading error is pointing right of runway: increase rudder gently; negative heading error decrease. Damp yaw rate and beta sideslip. Near alignment use trim.",
    "throttle": "Select ABSOLUTE throttle for C172 approach. Aim approach airspeed 30 m/s; use about 0.5 at 30 m/s, add power if slow, reduce if fast. During FLARE reduce throttle to 0.25 or less during flare. Do not cut early while still high. Touchdown ideal airspeed 28m/s.",
}
CRITERIA = {
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
NEAR_GROUND_ELEVATOR = [
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

NEAR_GROUND_ELEVATOR_INSTRUCTIONS = "Choose ABSOLUTE elevator near ground (FLARE or ROLLOUT). More negative pitches nose UP, more positive nose DOWN. Choose by actual vertical speed; aim a modest nose-up attitude and controlled shallow descent, not a float or climb. On ground, allow the nose to settle gently."
DECISION_SUFFIX = " Use current `flight` and `runway` state to choose one matching physical correction; do not select trim when the aircraft is diverging."
AXES = tuple(COMMANDS)


class SharedActionDecision(BaseModel):
    """Exactly one canonical string action ID for each actuator."""

    model_config = ConfigDict(extra="forbid", strict=True)

    aileron: Literal["0", "1", "2", "3", "4", "5", "6"]
    elevator: Literal["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]
    rudder: Literal["0", "1", "2", "3", "4", "5", "6"]
    throttle: Literal["0", "1", "2", "3", "4", "5", "6"]


def criteria_for_phase(phase: str) -> dict[str, list[str]]:
    """Return the active frozen criteria for APPROACH, FLARE, or ROLLOUT."""
    if phase not in {"APPROACH", "FLARE", "ROLLOUT"}:
        raise ValueError(f"Unknown flight phase: {phase}")
    return {
        axis: NEAR_GROUND_ELEVATOR if axis == "elevator" and phase != "APPROACH" else criteria
        for axis, criteria in CRITERIA.items()
    }


def canonical_observation(observation: Mapping[str, Any] | BaseModel) -> dict[str, Any]:
    """Build the one observation shape supplied to every official AI adapter."""
    obs = observation.model_dump(mode="json") if isinstance(observation, BaseModel) else observation
    status = dict(obs.get("status", {}))
    runway = dict(obs["runway"])
    altitude = runway.get("altitude_agl_m")
    phase = (
        "ROLLOUT"
        if status.get("on_ground")
        else ("FLARE" if altitude is not None and altitude < FLARE_ALTITUDE_AGL_M else "APPROACH")
    )
    return {
        "flight": dict(obs["flight"]),
        "runway": runway,
        "current_controls": dict(obs.get("controls", {})),
        "time_s": obs.get("time_s", 0.0),
        "motion": dict(obs.get("temporal", {}).get("rates", {})),
        "status": status,
        "phase": phase,
    }


def _active_axes(phase: str) -> dict[str, dict[str, Any]]:
    active = criteria_for_phase(phase)
    return {
        axis: {
            "instructions": (
                NEAR_GROUND_ELEVATOR_INSTRUCTIONS
                if axis == "elevator" and phase != "APPROACH"
                else INSTRUCTIONS[axis] + DECISION_SUFFIX
            ),
            "actions": [
                {"id": str(i), "command": command, "criterion": active[axis][i]}
                for i, command in enumerate(COMMANDS[axis])
            ],
        }
        for axis in AXES
    }


def action_space() -> dict[str, Any]:
    """Return the complete v1 definition used for serialization and hashing."""
    return {
        "benchmark_protocol": BENCHMARK_PROTOCOL,
        "action_space_version": ACTION_SPACE_VERSION,
        "phase_selection": [
            {"phase": "ROLLOUT", "when": "status.on_ground == true"},
            {
                "phase": "FLARE",
                "when": (
                    f"status.on_ground != true and runway.altitude_agl_m < {FLARE_ALTITUDE_AGL_M}"
                ),
            },
            {"phase": "APPROACH", "when": "otherwise"},
        ],
        "phases": {phase: _active_axes(phase) for phase in ("APPROACH", "FLARE", "ROLLOUT")},
    }


def action_space_json() -> str:
    return json.dumps(action_space(), sort_keys=True, separators=(",", ":"))


ACTION_SPACE_SHA256 = hashlib.sha256(action_space_json().encode()).hexdigest()


def protocol_metadata() -> dict[str, str]:
    return {
        "benchmark_protocol": BENCHMARK_PROTOCOL,
        "action_space_version": ACTION_SPACE_VERSION,
        "action_space_sha256": ACTION_SPACE_SHA256,
    }


def build_llm_control_prompt(phase: str) -> str:
    """Render the active canonical semantics for a categorical model adapter."""
    active = {
        "benchmark_protocol": BENCHMARK_PROTOCOL,
        "action_space_version": ACTION_SPACE_VERSION,
        "phase": phase,
        "actuators": _active_axes(phase),
    }
    return (
        "FlightBench evaluates a JSBSim C172 runway landing. Use only the supplied canonical "
        "observation. Select exactly one action ID for each actuator from the canonical choices "
        "below. Commands are absolute target positions, not deltas; JSBSim computes aircraft "
        "motion. Return one JSON object containing exactly aileron, elevator, rudder, and throttle "
        "as string action IDs. No prose or markdown.\n"
        + json.dumps(active, sort_keys=True, separators=(",", ":"))
    )


def command_from_action_ids(
    decision: Mapping[str, Any] | SharedActionDecision,
) -> ControlCommand:
    """Strictly validate canonical IDs and map them to absolute commands."""
    validated = SharedActionDecision.model_validate(
        decision.model_dump() if isinstance(decision, SharedActionDecision) else decision
    )
    ids = validated.model_dump()
    return ControlCommand(**{axis: COMMANDS[axis][int(ids[axis])] for axis in AXES})
