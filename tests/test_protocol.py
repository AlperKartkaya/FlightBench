import json

import pytest
from pydantic import ValidationError

from flightbench.protocol import (
    ACTION_SPACE_SHA256,
    ACTION_SPACE_VERSION,
    BENCHMARK_PROTOCOL,
    COMMANDS,
    CRITERIA,
    FLARE_ALTITUDE_AGL_M,
    NEAR_GROUND_ELEVATOR,
    SharedActionDecision,
    action_space_json,
    build_llm_control_prompt,
    canonical_observation,
    command_from_action_ids,
    protocol_metadata,
)

VALID_ACTION = {"aileron": "3", "elevator": "7", "rudder": "3", "throttle": "3"}


def test_frozen_v1_snapshot_is_deterministic():
    serialized = action_space_json()
    assert serialized == json.dumps(json.loads(serialized), sort_keys=True, separators=(",", ":"))
    assert ACTION_SPACE_SHA256 == "5b7d181a8a9dc7a934ef4e2efba5e36772f5bbce1f3af847d6547abdf64c76d9"
    assert f"< {FLARE_ALTITUDE_AGL_M}" in serialized
    assert protocol_metadata() == {
        "benchmark_protocol": BENCHMARK_PROTOCOL,
        "action_space_version": ACTION_SPACE_VERSION,
        "action_space_sha256": ACTION_SPACE_SHA256,
    }


def test_v1_preserves_jev_commands_and_phase_specific_elevator_rules():
    assert COMMANDS == {
        "aileron": [-0.35, -0.25, -0.2, -0.15, -0.1, -0.05, 0.05],
        "elevator": [-0.3, -0.2, -0.1, -0.05, 0, 0.05, 0.1, 0.15, 0.2, 0.25],
        "rudder": [-0.1, 0, 0.05, 0.09, 0.13, 0.18, 0.28],
        "throttle": [0, 0.25, 0.4, 0.5, 0.65, 0.8, 1],
    }
    assert len(CRITERIA["elevator"]) == len(NEAR_GROUND_ELEVATOR) == len(COMMANDS["elevator"])


@pytest.mark.parametrize(
    "invalid",
    [
        VALID_ACTION | {"aileron": "99"},
        {key: value for key, value in VALID_ACTION.items() if key != "rudder"},
        VALID_ACTION | {"spoilers": "0"},
        VALID_ACTION | {"throttle": 3},
    ],
)
def test_action_decision_strictly_rejects_unknown_missing_extra_and_non_string_ids(invalid):
    with pytest.raises(ValidationError):
        SharedActionDecision.model_validate(invalid)


def test_action_ids_map_to_frozen_absolute_commands():
    assert command_from_action_ids(VALID_ACTION).model_dump() == {
        "aileron": -0.15,
        "elevator": 0.15,
        "rudder": 0.09,
        "throttle": 0.5,
    }

    bypassed = SharedActionDecision.model_construct(**(VALID_ACTION | {"aileron": "99"}))
    with pytest.raises(ValidationError):
        command_from_action_ids(bypassed)


def test_canonical_observation_normalizes_phase_for_every_ai_adapter():
    observation = {
        "flight": {"airspeed_mps": 30.0},
        "runway": {"altitude_agl_m": 8.0},
        "controls": {"aileron": -0.15},
        "temporal": {"rates": {"cross_track_rate_mps": 1.0}},
        "status": {"on_ground": False},
        "time_s": 12.5,
    }
    assert canonical_observation(observation) == {
        "flight": observation["flight"],
        "runway": observation["runway"],
        "current_controls": observation["controls"],
        "time_s": 12.5,
        "motion": observation["temporal"]["rates"],
        "status": observation["status"],
        "phase": "FLARE",
    }

    observation["runway"]["altitude_agl_m"] = FLARE_ALTITUDE_AGL_M
    assert canonical_observation(observation)["phase"] == "APPROACH"
    observation["status"]["on_ground"] = True
    assert canonical_observation(observation)["phase"] == "ROLLOUT"


def test_llm_prompt_uses_the_same_phase_specific_criteria_as_jev():
    prompt = build_llm_control_prompt("FLARE")
    assert NEAR_GROUND_ELEVATOR[0] in prompt
    assert CRITERIA["elevator"][0] not in prompt
