import json
from copy import deepcopy

import pytest

from examples.rescore_episode import main, replay_and_rescore
from flightbench.core import ControlCommand
from flightbench.environment import FixedWingLandingEnv
from flightbench.scoring import ScoringConfig


def _record(mode="lockstep"):
    scoring = ScoringConfig()
    env = FixedWingLandingEnv(scoring=scoring, decision_hz=2)
    observation, _ = env.reset(seed=42)
    initial = deepcopy(observation)
    decisions = []
    commands = (
        ControlCommand(aileron=-0.15, elevator=0.15, rudder=0.09, throttle=0.5),
        ControlCommand(aileron=-0.2, elevator=0.2, rudder=0.05, throttle=0.4),
    )
    ticks = (0, 60) if mode == "lockstep" else (7, 53)
    action = ControlCommand(aileron=-0.15, elevator=0.17, rudder=0.09, throttle=0.5)
    for tick in range(120):
        if tick in ticks:
            action = commands[ticks.index(tick)]
            decisions.append(
                {
                    "applied_sim_time_s": tick / 120,
                    "applied": True,
                    "control_after": action.model_dump(),
                    "error": None,
                }
            )
        env.advance(action, ticks=1)
    final_state = env.snapshot()
    env.close()
    return {
        "type": "episode",
        "run_id": f"test-{mode}",
        "config": {
            "scenario": "easy",
            "seed": 42,
            "decision_hz": 2,
            "mode": mode,
            "scoring_version": "v2",
        },
        "initial_observation": initial,
        "final_state": final_state,
        "decisions": decisions,
    }


@pytest.mark.parametrize("mode", ["lockstep", "realtime"])
def test_replay_exactly_reproduces_physics_without_a_controller(mode):
    record = _record(mode)
    result = replay_and_rescore(record)
    assert result["physics_replay_verified"] is True
    assert result["recorded_result"] == result["rescored_result"]


def test_rescore_uses_new_scoring_but_preserves_source_record():
    record = _record()
    original = deepcopy(record)
    changed = ScoringConfig(lateral_normalization_m=20)
    result = replay_and_rescore(record, changed)
    assert (
        result["rescored_result"]["trajectory_error_integrals"]["lateral"]
        < result["recorded_result"]["trajectory_error_integrals"]["lateral"]
    )
    assert record == original


def test_replay_fails_closed_on_a_changed_command():
    record = _record()
    record["decisions"][0]["control_after"]["elevator"] = -0.2
    with pytest.raises(ValueError, match="physics replay mismatch"):
        replay_and_rescore(record)


def test_cli_will_not_overwrite_output(tmp_path):
    source = tmp_path / "episode.json"
    output = tmp_path / "rescored.json"
    source.write_text(json.dumps(_record()))
    output.write_text("keep")
    with pytest.raises(FileExistsError):
        main([str(source), "--output", str(output)])
    assert output.read_text() == "keep"


def test_cli_emits_only_json(tmp_path):
    import subprocess
    import sys

    source = tmp_path / "episode.json"
    source.write_text(json.dumps(_record("realtime")))
    completed = subprocess.run(
        [sys.executable, "examples/rescore_episode.py", str(source)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout)["physics_replay_verified"] is True
