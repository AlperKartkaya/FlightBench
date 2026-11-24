"""Twenty new easy flights on Colab, with continuous/apply-on-arrival realtime."""

import argparse
import fcntl
import gzip
import hashlib
import json
import os
import runpy
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from examples import run_glide_campaign as common
from examples.rescore_episode import load_record
from examples.run_ten_trial_campaign import SEEDS, verify_episode
from flightbench.benchmark import run_episode
from flightbench.protocol import protocol_metadata
from flightbench.runs import now, source_identity

NAME = "2026-11-20-glide-v1.2-easy-20-continuous"
DATA = ROOT / "leaderboard/campaigns" / NAME
EVIDENCE = ROOT / "docs/evaluations" / NAME
MODES = ("realtime", "lockstep")


def schedule(mode):
    return "continuous" if mode == "realtime" else "fixed"


def save(name, value):
    common.EVIDENCE = EVIDENCE
    common.save(name, value)


def trial(mode, seed, folder):
    folder.mkdir(parents=True, exist_ok=False)
    os.environ["FLIGHTBENCH_DECISION_LOG"] = str(folder / "provider.jsonl")
    run_episode(
        common.CONTROLLER,
        seed,
        mode=mode,
        scenario="easy",
        model="glide-v1.2",
        reasoning_effort="low",
        decision_hz=2,
        decision_schedule=schedule(mode),
        time_scale=1.0,
        realtime_response_policy="apply-on-arrival",
        timeout_s=300,
        record_dir=folder,
    )


def load_trial(folder):
    paths = [p for p in folder.glob("*.json") if json.loads(p.read_text()).get("type") == "episode"]
    assert len(paths) == 1, (
        "Inspect incomplete attempt; never automatically retry a physical flight"
    )
    record = load_record(paths[0])
    compressed = paths[0].with_suffix(".json.gz")
    if not compressed.exists():
        compressed.write_bytes(gzip.compress(paths[0].read_bytes(), mtime=0))
    assert record == json.loads(gzip.decompress(compressed.read_bytes()))
    return record


def verify(folder, mode, seed, frozen, audit):
    record = load_trial(folder)
    cfg = record["config"]
    assert cfg["decision_schedule"] == schedule(mode)
    assert cfg["realtime_response_policy"] == "apply-on-arrival"
    assert cfg["scoring_version"] == "v2"
    assert all(cfg[k] == v for k, v in protocol_metadata().items())
    assert (
        cfg["controller_metadata"]["adapter_sha256"]
        == frozen["file_hashes"]["examples/controllers/glide.py"]
    )
    assert (
        cfg["controller_metadata"]["model_revision"] == "19a948f812af30c8962337fbbec2472e575eee7d"
    )
    row = verify_episode(record, folder, common.group(mode), seed, frozen["identity"])
    provider = audit(record, folder, common.group(mode))
    raw = [json.loads(line) for line in (folder / "provider.jsonl").read_text().splitlines()]
    assert all(r["status"] == 200 and not r.get("exception_type") for r in raw)
    assert record["diagnostics"]["stale_decisions"] == 0
    assert all(d.get("applied", True) and not d.get("error") for d in record["decisions"])
    if mode == "realtime":
        # A new observation is sent on the same physics tick that applied the last answer.
        for decision, request in zip(record["decisions"], raw[1:]):
            assert decision["applied_sim_time_s"] == request["request"]["state"]["time_s"]
    row.update(
        input_question_answer_audit=True,
        mean_provider_latency_ms=statistics.mean(r["latency_ms"] for r in raw),
        median_provider_latency_ms=statistics.median(r["latency_ms"] for r in raw),
        decision_schedule=schedule(mode),
        realtime_response_policy="apply-on-arrival",
        strict_leaderboard_manifest_validated=False,
    )
    save(f"provider-audit-{mode}-{seed}.json", provider)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", choices=MODES)
    parser.add_argument("--seed", type=int, choices=SEEDS)
    parser.add_argument("--folder", type=Path)
    args = parser.parse_args()
    if args.trial:
        assert args.seed is not None and args.folder is not None
        trial(args.trial, args.seed, args.folder)
        return
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    with (EVIDENCE / "runner.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        frozen = json.loads((EVIDENCE / "source.json").read_text())
        revision = EVIDENCE / "runner-revision.json"
        if revision.exists():
            frozen["file_hashes"].update(json.loads(revision.read_text())["file_hashes"])
        assert source_identity()["source_hash"] == frozen["identity"]["source_hash"]
        assert all(
            hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h
            for p, h in frozen["file_hashes"].items()
        )
        status_path = EVIDENCE / "status.json"
        status = (
            json.loads(status_path.read_text())
            if status_path.exists()
            else {
                "state": "running",
                "started_at": now(),
                "planned_runs": 20,
                "seeds": list(SEEDS),
                "groups": {m: [] for m in MODES},
                "protocol": "Realtime continuous, apply-on-arrival, 1x; lockstep fixed 2 Hz. Easy only.",
                "provenance_limit": "Remote Git metadata unavailable; frozen source hashes and raw episode audits retained, no strict leaderboard submission claimed.",
            }
        )
        status.pop("error", None)
        status.pop("stopped_at", None)
        audit = runpy.run_path(
            str(ROOT / "docs/evaluations/2026-11-15-ten-trial-easy/audit_provider.py")
        )["audit_episode"]
        try:
            common.EVIDENCE = EVIDENCE
            if not (EVIDENCE / "preflight.json").exists():
                common.preflight()
            for mode in MODES:
                for seed in SEEDS:
                    if any(r["seed"] == seed for r in status["groups"][mode]):
                        continue
                    status.update(state="running", current={"mode": mode, "seed": seed})
                    save("status.json", status)
                    folder = DATA / mode / str(seed)
                    if not folder.exists():
                        folder.parent.mkdir(parents=True, exist_ok=True)
                        with folder.with_suffix(".log").open("x") as log:
                            child = subprocess.run(
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
                        assert child.returncode == 0, (
                            "Child failed; inspect retained attempt before resuming"
                        )
                    row = verify(folder, mode, seed, frozen, audit)
                    status["groups"][mode].append(row)
                    save("status.json", status)
                    save(
                        "summary.json",
                        {m: common.summarize(rows) for m, rows in status["groups"].items()},
                    )
                    print(json.dumps({"mode": mode, **row}), flush=True)
            assert all(len(v) == 10 for v in status["groups"].values())
            assert len({r["run_id"] for rows in status["groups"].values() for r in rows}) == 20
            status.update(state="complete", finished_at=now())
            status.pop("current", None)
        except Exception as error:
            status.update(state="incomplete", error=type(error).__name__, stopped_at=now())
            raise
        finally:
            save("status.json", status)


if __name__ == "__main__":
    main()
