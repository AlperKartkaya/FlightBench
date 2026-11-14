"""Run and replay three serial Azure Decision flights, retaining all evidence."""

import argparse
import fcntl
import gzip
import hashlib
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from examples.controllers.azure_decision import MODEL
from examples.rescore_episode import (
    _assert_same,
    _silence_native_stdout,
    _transition_schedule,
    replay_and_rescore,
)
from flightbench.core import PHYSICS_HZ, TRIM_AILERON, TRIM_ELEVATOR, TRIM_RUDDER, ControlCommand
from flightbench.environment import FixedWingLandingEnv
from flightbench.leaderboard import validate_submission
from flightbench.protocol import action_space, canonical_observation, command_from_action_ids
from flightbench.runs import SOURCE_FILES, now, source_identity
from flightbench.scoring import ScoringConfig
from flightbench.temporal import TelemetryHistory

WORK = ROOT / "scratch/decision-1-2026-11-11"
DATA = ROOT / "leaderboard/campaigns/2026-11-11-microsoft-decision-1"
EVIDENCE = ROOT / "docs/local-model-runtime/decision-1-2026-11-11"
ADAPTER = ROOT / "examples/controllers/azure_decision.py"
SEEDS = (42, 101, 202)
MODE = "lockstep"


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temp.replace(path)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def realtime_inputs(episode, requests):
    """Reconstruct per-physics-tick motion, including requests unfinished at termination."""
    final_tick = round(episode["final_state"]["observation"]["time_s"] * PHYSICS_HZ)
    schedule = _transition_schedule(episode, final_tick)
    by_tick = {}
    for request in requests:
        tick = round(request["state"]["time_s"] * PHYSICS_HZ)
        assert tick not in by_tick and 0 <= tick < final_tick
        by_tick[tick] = request
    with _silence_native_stdout():
        env = FixedWingLandingEnv(
            scenario=episode["config"]["scenario"],
            decision_hz=2,
            scoring=ScoringConfig(**episode["final_state"]["result"]["scoring"]),
        )
        try:
            observation, _ = env.reset(seed=episode["config"]["seed"])
            telemetry = TelemetryHistory()
            telemetry.add(observation)
            action = ControlCommand(
                aileron=TRIM_AILERON, elevator=TRIM_ELEVATOR, rudder=TRIM_RUDDER, throttle=0.5
            )
            checked = 0
            while env.ticks < final_tick:
                if env.ticks in by_tick:
                    expected = canonical_observation(
                        observation | {"temporal": telemetry.features(observation)}
                    )
                    _assert_same(expected, by_tick[env.ticks]["state"], "request_state")
                    checked += 1
                if env.ticks in schedule:
                    action = schedule[env.ticks]
                observation, _, _, _, _ = env.advance(action, ticks=1)
                telemetry.add(observation)
            assert checked == len(requests)
            _assert_same(episode["final_state"], env.snapshot(), "final_state")
        finally:
            env.close()


def verify(folder, seed, identity):
    submission = validate_submission(json.loads((folder / "submission.json").read_text()), folder)
    assert submission.flightbench.source_hash == identity["source_hash"]
    assert len(submission.artifacts) == 1
    with gzip.open(folder / submission.artifacts[0].path, "rt") as handle:
        episode = json.load(handle)
    config = episode["config"]
    assert (config["seed"], config["mode"], config["model"], config["decision_hz"]) == (
        seed,
        MODE,
        MODEL,
        2,
    )
    assert config["controller_metadata"]["adapter_sha256"] == sha(ADAPTER)
    assert config["time_scale"] == 1.0
    if MODE == "realtime":
        assert config["realtime_response_policy"] == "discard-stale"
    assert episode["diagnostics"]["api_errors"] == 0
    assert episode["outcome"]["status"] in {
        "landed",
        "runway_excursion",
        "out_of_bounds",
        "nose_first_contact",
        "crash",
        "time_limit",
    }
    rows = [
        json.loads(line) for line in (WORK / f"seed-{seed}.requests.jsonl").read_text().splitlines()
    ]
    successful = [r for r in rows if r.get("status") == 200]
    if MODE == "realtime":
        requests = [r["request"] for r in rows if r["attempt"] == 1]
        diagnostics = episode["diagnostics"]
        assert (
            len(requests)
            == diagnostics["requests_started"] - diagnostics["requests_cancelled_before_start"]
        )
        assert len(successful) == len(requests)
        assert len(episode["decisions"]) <= len(successful)
        realtime_inputs(episode, requests)
    else:
        assert len(successful) == len(episode["decisions"])
    telemetry = TelemetryHistory()
    for decision, raw in zip(
        episode["decisions"], successful[: len(episode["decisions"])], strict=True
    ):
        observation = decision["observation"]
        telemetry.add(observation)
        enriched = observation | {"temporal": telemetry.features(observation)}
        if MODE == "lockstep":
            assert raw["request"]["state"] == canonical_observation(enriched)
        assert raw["request"]["state"]["time_s"] == decision["observation_sim_time_s"]
        axes = action_space()["phases"][raw["request"]["state"]["phase"]]
        assert raw["request"]["questions"] == {
            axis: {
                "type": "choice",
                "instructions": spec["instructions"],
                "criteria": {a["id"]: a["criterion"] for a in spec["actions"]},
            }
            for axis, spec in axes.items()
        }
        ids = decision["decision_info"]["action_ids"]
        assert ids == {
            axis: answer["choice"] for axis, answer in raw["response"]["answers"].items()
        }
        if decision.get("applied", True):
            assert (
                command_from_action_ids(ids).model_dump()
                == decision["action"]
                == decision["control_after"]
            )
        else:
            assert decision["control_before"] == decision["control_after"] == decision["action"]
    replay = replay_and_rescore(episode)
    _assert_same(replay["recorded_result"], replay["rescored_result"])
    write(EVIDENCE / f"seed-{seed}.replay.json", replay)
    raw_path = EVIDENCE / f"seed-{seed}.requests.jsonl.gz"
    raw_path.write_bytes(
        gzip.compress((WORK / f"seed-{seed}.requests.jsonl").read_bytes(), mtime=0)
    )
    usage = {
        key: sum(r["response"]["usage"][key] for r in successful)
        for key in ("input_tokens", "output_tokens")
    }
    return {
        "seed": seed,
        "run_id": episode["run_id"],
        **episode["outcome"],
        "diagnostics": episode["diagnostics"],
        "usage": usage,
        "http_attempts": len(rows),
        "http_retries": len(rows) - len(successful),
        "requests_sha256": sha(raw_path),
        "replay_verified": True,
        "started_at": episode["started_at"],
        "finished_at": episode["finished_at"],
    }


def main(mode="lockstep"):
    global MODE, WORK, DATA, EVIDENCE
    MODE = mode
    if mode == "realtime":
        WORK = ROOT / "scratch/decision-1-realtime-2026-11-11"
        DATA = ROOT / "leaderboard/campaigns/2026-11-11-microsoft-decision-1-realtime"
        EVIDENCE = ROOT / "docs/local-model-runtime/decision-1-realtime-2026-11-11"
    WORK.mkdir(parents=True, exist_ok=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    with (WORK / "runner.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        identity = source_identity()
        provenance = EVIDENCE / "source.json"
        if not provenance.exists():
            archive = EVIDENCE / "benchmark-source.tar.gz"
            with tarfile.open(archive, "x:gz") as tar:
                for path in (
                    *SOURCE_FILES,
                    ADAPTER,
                    Path(__file__),
                    ROOT / "tests/test_azure_decision.py",
                ):
                    tar.add(path, arcname=path.relative_to(ROOT))
            write(
                provenance,
                {
                    "identity": identity,
                    "archive_sha256": sha(archive),
                    "adapter_sha256": sha(ADAPTER),
                    "runner_sha256": sha(Path(__file__)),
                },
            )
        frozen = json.loads(provenance.read_text())
        assert frozen["identity"]["source_hash"] == identity["source_hash"]
        assert frozen["adapter_sha256"] == sha(ADAPTER)
        status = {
            "state": "running",
            "mode": MODE,
            "started_at": now(),
            "seeds": list(SEEDS),
            "runs": [],
        }
        try:
            for seed in SEEDS:
                assert source_identity()["source_hash"] == identity["source_hash"]
                folder = DATA / str(seed)
                raw = WORK / f"seed-{seed}.requests.jsonl"
                if not (folder / "submission.json").exists():
                    if folder.exists() or raw.exists():
                        raise RuntimeError("Partial evidence retained; inspect before resuming")
                    status["current_seed"] = seed
                    write(WORK / "status.json", status)
                    command = [
                        sys.executable,
                        "-u",
                        "-m",
                        "flightbench.benchmark",
                        "eval",
                        "--controller",
                        "examples.controllers.azure_decision:AzureDecisionController",
                        "--model",
                        MODEL,
                        "--modes",
                        MODE,
                        "--realtime-response-policy",
                        "discard-stale",
                        "--seeds",
                        str(seed),
                        "--scenario",
                        "easy",
                        "--decision-hz",
                        "2",
                        "--time-scale",
                        "1.0",
                        "--timeout",
                        "120",
                        "--jobs",
                        "1",
                        "--output-dir",
                        str(folder),
                    ]
                    with (WORK / f"seed-{seed}.log").open("x") as log:
                        subprocess.run(
                            command,
                            cwd=ROOT,
                            env=os.environ | {"FLIGHTBENCH_AZURE_LOG": str(raw)},
                            stdout=log,
                            stderr=subprocess.STDOUT,
                            check=True,
                        )
                row = verify(folder, seed, identity)
                status["runs"].append(row)
                write(WORK / "status.json", status)
                print(json.dumps(row), flush=True)
            status.update(state="complete", finished_at=now())
            status.pop("current_seed", None)
            write(EVIDENCE / "verification.json", status)
        except Exception as error:
            status.update(state="failed", exception_type=type(error).__name__, failed_at=now())
            raise
        finally:
            write(WORK / "status.json", status)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("lockstep", "realtime"), default="lockstep")
    main(parser.parse_args().mode)
