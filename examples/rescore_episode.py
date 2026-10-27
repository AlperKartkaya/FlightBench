"""Replay a recorded episode without calling its controller, then rescore it."""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import sys
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import asdict
from numbers import Real
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flightbench.core import (
    PHYSICS_HZ,
    TRIM_AILERON,
    TRIM_ELEVATOR,
    TRIM_RUDDER,
    ControlCommand,
)
from flightbench.environment import FixedWingLandingEnv
from flightbench.scoring import ScoringConfig, evaluate, trajectory_error_rate


@contextmanager
def _silence_native_stdout():
    """Disable the simulator banner before constructing its native engine."""
    previous = os.environ.get("JSBSIM_DEBUG")
    os.environ["JSBSIM_DEBUG"] = "0"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("JSBSIM_DEBUG", None)
        else:
            os.environ["JSBSIM_DEBUG"] = previous


def load_record(path: Path) -> dict:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as source:
        record = json.load(source)
    if not isinstance(record, dict) or record.get("type") != "episode":
        raise ValueError("input must be one complete FlightBench episode record")
    return record


def _assert_same(expected: Any, actual: Any, path: str = "record") -> None:
    if isinstance(expected, bool) or isinstance(actual, bool):
        if expected is not actual:
            raise ValueError(f"physics replay mismatch at {path}: {actual!r} != {expected!r}")
    elif isinstance(expected, Real) and isinstance(actual, Real):
        if not math.isclose(float(actual), float(expected), rel_tol=1e-10, abs_tol=1e-10):
            raise ValueError(f"physics replay mismatch at {path}: {actual!r} != {expected!r}")
    elif isinstance(expected, Mapping) and isinstance(actual, Mapping):
        if set(expected) != set(actual):
            raise ValueError(f"physics replay keys differ at {path}")
        for key in expected:
            _assert_same(expected[key], actual[key], f"{path}.{key}")
    elif isinstance(expected, list) and isinstance(actual, (list, tuple)):
        if len(expected) != len(actual):
            raise ValueError(f"physics replay length differs at {path}")
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual, strict=True)):
            _assert_same(expected_item, actual_item, f"{path}[{index}]")
    elif expected != actual:
        raise ValueError(f"physics replay mismatch at {path}: {actual!r} != {expected!r}")


def _transition_schedule(record: Mapping, final_tick: int) -> dict[int, ControlCommand]:
    schedule = {}
    for decision in record.get("decisions", []):
        if decision.get("error") or not decision.get("applied", True):
            continue
        applied_time = decision.get("applied_sim_time_s")
        command = decision.get("control_after") or decision.get("action")
        if not isinstance(applied_time, Real) or isinstance(applied_time, bool) or not command:
            raise ValueError("every applied decision needs its simulation time and control command")
        tick = round(float(applied_time) * PHYSICS_HZ)
        if not math.isclose(float(applied_time), tick / PHYSICS_HZ, abs_tol=1e-9):
            raise ValueError("applied decision time is not on a physics tick")
        if tick >= final_tick or tick in schedule:
            raise ValueError("applied decisions must occupy unique ticks before the final state")
        schedule[tick] = ControlCommand.model_validate(command)
    return schedule


def replay_and_rescore(record: Mapping, scoring: ScoringConfig | None = None) -> dict:
    """Replay recorded commands under original physics; use recorded success for rescoring.

    The replay uses the record's scoring configuration for termination behavior. The requested
    scoring configuration only recomputes trajectory integrals and the final score. Therefore a
    changed safety rule may turn a recorded success into a failure, but a recorded failure cannot
    become a success.
    """
    config = record.get("config") or {}
    final_state = record.get("final_state") or {}
    recorded_result = final_state.get("result") or {}
    recorded_scoring = recorded_result.get("scoring")
    final_observation = final_state.get("observation") or {}
    if config.get("scoring_version") != "v2" or not isinstance(recorded_scoring, dict):
        raise ValueError("offline physics replay requires a V2 record with its scoring config")
    if not isinstance(record.get("decisions"), list) or "time_s" not in final_observation:
        raise ValueError("offline physics replay requires decisions and a final simulation time")

    original_scoring = ScoringConfig(**recorded_scoring)
    target_scoring = scoring or ScoringConfig()
    final_tick = round(float(final_observation["time_s"]) * PHYSICS_HZ)
    if not math.isclose(float(final_observation["time_s"]), final_tick / PHYSICS_HZ, abs_tol=1e-9):
        raise ValueError("final simulation time is not on a physics tick")
    schedule = _transition_schedule(record, final_tick)

    with _silence_native_stdout():
        env = FixedWingLandingEnv(
            scenario=config.get("scenario", "easy"),
            max_time_s=120,
            scoring=original_scoring,
            decision_hz=config.get("decision_hz", 2),
        )
        try:
            initial_observation, _ = env.reset(seed=config.get("seed"))
            _assert_same(
                record.get("initial_observation"), initial_observation, "initial_observation"
            )
            action = ControlCommand(
                aileron=TRIM_AILERON,
                elevator=TRIM_ELEVATOR,
                rudder=TRIM_RUDDER,
                throttle=0.5,
            )
            target_integrals = {"lateral": 0.0, "pitch": 0.0, "glide": 0.0}
            used_transitions = set()
            while env.ticks < final_tick:
                if env.done:
                    raise ValueError("physics replay ended before the recorded final state")
                if env.ticks in schedule:
                    action = schedule[env.ticks]
                    used_transitions.add(env.ticks)
                before_touchdown = env.touchdown is None
                observation, _, _, _, _ = env.advance(action, ticks=1)
                if before_touchdown and target_scoring.version == "v2":
                    for name, rate in trajectory_error_rate(observation, target_scoring).items():
                        target_integrals[name] += rate / PHYSICS_HZ

            if used_transitions != set(schedule):
                raise ValueError("not every recorded control transition was replayed")
            replayed_state = env.snapshot()
            _assert_same(final_state, replayed_state, "final_state")
        finally:
            env.close()

    rescored = evaluate(
        replayed_state["result"].get("touchdown"),
        recorded_result.get("success", False),
        recorded_result.get("reason", "unknown"),
        target_scoring,
        target_integrals,
    )
    return {
        "schema_version": 1,
        "source_run_id": record.get("run_id"),
        "physics_replay_verified": True,
        "replayed_physics_ticks": final_tick,
        "applied_control_transitions": len(schedule),
        "recorded_result": recorded_result,
        "rescored_result": rescored,
        "target_scoring": asdict(target_scoring),
        "outcome_semantics": (
            "Recorded success is authoritative; target safety checks may only disqualify it."
        ),
    }


def _scoring_config(path: Path | None) -> ScoringConfig:
    if path is None:
        return ScoringConfig()
    values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, dict):
        raise TypeError("scoring config must be a JSON object")
    return ScoringConfig(**values)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path, help="episode .json or .json.gz")
    parser.add_argument("--scoring-config", type=Path, help="complete ScoringConfig JSON object")
    parser.add_argument("--output", type=Path, help="new output file; existing files are preserved")
    args = parser.parse_args(argv)
    if args.output and args.output.exists():
        raise FileExistsError(args.output)
    result = replay_and_rescore(load_record(args.record), _scoring_config(args.scoring_config))
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            output.write(text)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
