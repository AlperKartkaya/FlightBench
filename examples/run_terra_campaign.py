"""Serial Terra trials; retain every attempt and retry a failed three-seed cohort once."""

from __future__ import annotations

import gzip
import hashlib
import json
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flightbench.benchmark import INCOMPLETE_STATUSES
from flightbench.leaderboard import validate_submission
from flightbench.runs import SOURCE_FILES, now, source_identity

EFFORTS = ("low", "medium", "high", "xhigh")
SEEDS = (42, 101, 202)
MODEL = "openai-codex/gpt-6.1-terra"
WORK = ROOT / "scratch/terra-v2-2026-10-28"
DATA = ROOT / "leaderboard/campaigns/2026-10-28-terra-v2"
EVIDENCE = ROOT / "docs/local-model-runtime/terra-v2-2026-10-28"


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    temp.replace(path)


def read_trial(folder, effort, seed, identity):
    sub = validate_submission(json.loads((folder / "submission.json").read_text()), folder)
    if sub.flightbench.source_hash != identity or len(sub.artifacts) != 1:
        raise ValueError("Trial source/artifact mismatch")
    path = folder / sub.artifacts[0].path
    with gzip.open(path, "rt") as handle:
        record = json.load(handle)
    cfg = record["config"]
    if (cfg["model"], cfg["reasoning_effort"], cfg["mode"], cfg["seed"]) != (
        MODEL,
        effort,
        "lockstep",
        seed,
    ):
        raise ValueError("Trial model/effort/mode/seed mismatch")
    if record["outcome"]["status"] in INCOMPLETE_STATUSES or record["diagnostics"]["api_errors"]:
        raise RuntimeError(
            "Infrastructure failure retained; inspect sanitized trial log before resume"
        )
    return record


def repeat_cohort(records):
    if len(records) != 3 or {r["config"]["seed"] for r in records} != set(SEEDS):
        raise ValueError("A cohort needs all three seeds")
    return not any(r["outcome"]["success"] for r in records)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    # OS-level exclusion also protects accidental manual/background double starts.
    import fcntl

    with (WORK / "runner.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        identity = source_identity()
        source = EVIDENCE / "source.json"
        if source.exists():
            if json.loads(source.read_text())["identity"]["source_hash"] != identity["source_hash"]:
                raise RuntimeError("Benchmark source changed; do not mix campaign revisions")
        else:
            archive = EVIDENCE / "benchmark-source.tar.gz"
            with tarfile.open(archive, "x:gz") as tar:
                for path in SOURCE_FILES:
                    tar.add(path, arcname=path.relative_to(ROOT))
            write(
                source,
                {
                    "identity": identity,
                    "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                    "pricing_source": "https://developers.openai.com/api/docs/models/gpt-6.1-terra",
                },
            )
        status = {"state": "running", "started_at": now(), "efforts": {}}
        for effort in EFFORTS:
            records = []
            for cohort in (1, 2):
                batch = []
                for seed in SEEDS:
                    if source_identity()["source_hash"] != identity["source_hash"]:
                        raise RuntimeError("Benchmark source changed during campaign")
                    folder = DATA / effort / f"cohort-{cohort}" / str(seed)
                    if not (folder / "submission.json").exists():
                        if folder.exists():
                            raise RuntimeError(
                                f"Unfinished evidence retained at {folder}; do not overwrite"
                            )
                        metadata = WORK / f"{effort}.json"
                        write(
                            metadata,
                            {
                                "name": f"GPT-6.1 Terra {effort}",
                                "slug": f"gpt-6-1-terra-{effort}",
                                "model": MODEL,
                                "provider": "OpenAI",
                                "reasoning_effort": effort,
                                "controller_type": "ai",
                                "license": "proprietary hosted API",
                                "local": False,
                                "source_url": "https://developers.openai.com/api/docs/models/gpt-6.1-terra",
                                "campaign": {
                                    "seeds": list(SEEDS),
                                    "retry": "Repeat all three seeds once only if no successful landing",
                                },
                            },
                        )
                        status.update(
                            current={
                                "effort": effort,
                                "cohort": cohort,
                                "seed": seed,
                                "started_at": now(),
                            }
                        )
                        write(WORK / "status.json", status)
                        command = [
                            str(ROOT / ".venv/bin/python"),
                            "-u",
                            str(
                                ROOT
                                / "docs/local-model-runtime/scoring-v2-2026-10-22/diagnostic_entry.py"
                            ),
                            "eval",
                            "--controller",
                            "codex",
                            "--model",
                            MODEL,
                            "--reasoning-effort",
                            effort,
                            "--metadata",
                            str(metadata),
                            "--modes",
                            "lockstep",
                            "--seeds",
                            str(seed),
                            "--scenario",
                            "easy",
                            "--decision-hz",
                            "2",
                            "--time-scale",
                            "1.0",
                            "--timeout",
                            "300",
                            "--jobs",
                            "1",
                            "--output-dir",
                            str(folder),
                        ]
                        with (WORK / f"{effort}-{cohort}-{seed}.log").open("x") as log:
                            subprocess.run(
                                command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True
                            )
                    record = read_trial(folder, effort, seed, identity["source_hash"])
                    records.append(record)
                    batch.append(record)
                    print(effort, cohort, seed, record["outcome"], flush=True)
                if not repeat_cohort(batch):
                    break
            best = max(records, key=lambda r: (r["outcome"]["quality"], -r["config"]["seed"]))
            status["efforts"][effort] = {
                "trials": len(records),
                "best_run_id": best["run_id"],
                "outcome": best["outcome"],
            }
            write(WORK / "status.json", status)
            # Publish only completed cohorts; this command never launches provider calls.
            subprocess.run(
                [
                    str(ROOT / ".venv/bin/python"),
                    str(ROOT / "examples/update_benchmark_additions.py"),
                ],
                cwd=ROOT,
                check=True,
            )
            subprocess.run(
                ["uv", "run", "--script", "examples/build_benchmark_visuals.py"],
                cwd=ROOT,
                check=True,
            )
        status.update(state="complete", finished_at=now())
        status.pop("current", None)
        write(WORK / "status.json", status)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # No provider error bodies or credentials in the durable status.
        write(WORK / "failure.json", {"exception_type": type(error).__name__, "at": now()})
        raise
