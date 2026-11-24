"""Six serial easy flights on Colab; raw payloads and offline replay are retained."""

import argparse
import fcntl
import hashlib
import json
import os
import runpy
import statistics
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from examples.controllers.glide import GlideController
from examples.rescore_episode import load_record
from examples.run_ten_trial_campaign import trial, verify_episode
from flightbench.environment import FixedWingLandingEnv
from flightbench.protocol import canonical_observation
from flightbench.runs import now, source_identity
from flightbench.temporal import TelemetryHistory

NAME = "2026-11-20-glide-v1.2-easy"
DATA = ROOT / "leaderboard/campaigns" / NAME
EVIDENCE = ROOT / "docs/evaluations" / NAME
SEEDS = (42, 101, 202)
MODES = ("realtime", "lockstep")
CONTROLLER = "examples.controllers.glide:GlideController"


def save(name, value):
    path = EVIDENCE / name
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def summarize(runs):
    success = [row for row in runs if row["success"]]
    return {
        "completed": len(runs),
        "successful_landings": len(success),
        "highest_score": max((r["quality"] for r in runs), default=None),
        "mean_all_runs": statistics.mean(r["quality"] for r in runs) if runs else None,
        "mean_successful_only": statistics.mean(r["quality"] for r in success) if success else None,
        "successful_only_denominator": len(success),
    }


def group(mode):
    return (f"glide-v1.2-{mode}", CONTROLLER, "glide-v1.2", mode)


def preflight():
    with urlopen("http://127.0.0.1:8000/health", timeout=5) as response:
        health = json.load(response)
    assert health["status"] == "ok" and health["model"] == "glide-v1.2"
    assert health["max_batch"] == 1
    env = FixedWingLandingEnv(scenario="easy", decision_hz=2)
    try:
        observation, _ = env.reset(seed=42)
        history = TelemetryHistory()
        history.add(observation)
        state = canonical_observation(observation | {"temporal": history.features(observation)})
    finally:
        env.close()
    os.environ["FLIGHTBENCH_DECISION_LOG"] = str(EVIDENCE / "warmup-provider.jsonl")
    controller = GlideController()
    actions = controller.decide(state)
    save(
        "preflight.json",
        {
            "at": now(),
            "health": health,
            "actions": actions,
            "note": "One initial-state model warmup; not a flight or scored trial.",
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", choices=MODES)
    parser.add_argument("--seed", type=int, choices=SEEDS)
    parser.add_argument("--folder", type=Path)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.trial:
        assert args.seed is not None and args.folder is not None
        trial(group(args.trial), args.seed, args.folder)
        return
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    with (EVIDENCE / "runner.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        frozen = json.loads((EVIDENCE / "source.json").read_text())
        assert source_identity()["source_hash"] == frozen["identity"]["source_hash"]
        revision = json.loads((EVIDENCE / "recovery-source.json").read_text())
        hashes = frozen["file_hashes"] | revision["file_hashes"]
        assert all(
            hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h for p, h in hashes.items()
        )
        status_path = EVIDENCE / "status.json"
        if status_path.exists():
            assert args.resume, "Existing attempt retained; use --resume after inspecting it"
            status = json.loads(status_path.read_text())
            assert status["state"] != "complete"
        else:
            assert not args.resume
            status = {
                "state": "running",
                "started_at": now(),
                "planned_runs": 6,
                "groups": {mode: [] for mode in MODES},
                "excluded": [],
            }
        save("status.json", status)
        audit = runpy.run_path(
            str(ROOT / "docs/evaluations/2026-11-15-ten-trial-easy/audit_provider.py")
        )["audit_episode"]
        try:
            if not (EVIDENCE / "preflight.json").exists():
                preflight()
            # Count the two already-completed seed-42 flights chronologically, not by score.
            slots = [
                ("realtime", 42, "42"),
                ("realtime", 42, "42-attempt-2"),
                ("realtime", 101, "101"),
                ("lockstep", 42, "42"),
                ("lockstep", 101, "101"),
                ("lockstep", 202, "202"),
            ]
            for mode, seed, name in slots:
                folder = DATA / mode / name
                relative = str(folder.relative_to(ROOT))
                if any(row["folder"] == relative for row in status["groups"][mode]):
                    continue
                status.update(state="running", current={"mode": mode, "seed": seed, "slot": name})
                save("status.json", status)
                if not folder.exists():
                    folder.parent.mkdir(parents=True, exist_ok=True)
                    with (folder.parent / f"{name}.log").open("x") as log:
                        subprocess.run(
                            [
                                sys.executable,
                                "-u",
                                str(Path(__file__)),
                                "--trial",
                                mode,
                                "--seed",
                                str(seed),
                                "--folder",
                                str(folder),
                            ],
                            cwd=ROOT,
                            check=False,
                            stdout=log,
                            stderr=subprocess.STDOUT,
                            timeout=1800,
                        )
                # A completed physical flight is never retried for an export error or score.
                records = list(folder.glob("*.json.gz"))
                assert len(records) == 1, "Inspect incomplete flight; no automatic retry"
                record = load_record(records[0])
                assert json.loads(records[0].with_suffix("").read_text()) == record
                log = (folder.parent / f"{name}.log").read_text()
                assert "submission.json" not in {p.name for p in folder.iterdir()}
                assert (
                    "episodes must share scenario, decision rate, source hash, and git commit"
                    in log
                )
                assert record["source_identity"]["git_commit"] is None
                row = verify_episode(record, folder, group(mode), seed, frozen["identity"])
                save(f"provider-audit-{mode}-{name}.json", audit(record, folder, group(mode)))
                raw = [
                    json.loads(line)
                    for line in (folder / "provider.jsonl").read_text().splitlines()
                ]
                assert all(r.get("status") == 200 and not r.get("exception_type") for r in raw)
                row["mean_provider_latency_ms"] = statistics.mean(r["latency_ms"] for r in raw)
                row["leaderboard_manifest_validated"] = False
                status["groups"][mode].append(row)
                save("status.json", status)
                save("summary.json", {m: summarize(rows) for m, rows in status["groups"].items()})
                print(json.dumps({"mode": mode, **row}), flush=True)
            assert all(len(rows) == 3 for rows in status["groups"].values())
            status.update(state="complete", finished_at=now())
        except Exception as error:
            status.update(state="incomplete", error=type(error).__name__, stopped_at=now())
            raise
        finally:
            if status["state"] == "complete":
                status.pop("current", None)
            save("status.json", status)


if __name__ == "__main__":
    main()
