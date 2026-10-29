"""One additional serial attempt per unsuccessful high/xhigh seed; preserve all evidence."""

from __future__ import annotations

import fcntl
import json
import subprocess

from run_terra_campaign import DATA, EVIDENCE, MODEL, ROOT, SEEDS, WORK, read_trial, write

from flightbench.runs import now, source_identity

RETRY_WORK = WORK / "landing-retry-1"


def main():
    RETRY_WORK.mkdir(parents=True, exist_ok=True)
    with (WORK / "runner.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        identity = json.loads((EVIDENCE / "source.json").read_text())["identity"]["source_hash"]
        if source_identity()["source_hash"] != identity:
            raise RuntimeError("Frozen benchmark source changed")
        plan = []
        for effort in ("high", "xhigh"):
            for seed in SEEDS:
                original = read_trial(
                    DATA / effort / "cohort-1" / str(seed), effort, seed, identity
                )
                if not original["outcome"]["success"]:
                    plan.append(
                        {"effort": effort, "seed": seed, "original_run_id": original["run_id"]}
                    )
        status = {"state": "running", "started_at": now(), "plan": plan, "completed": []}
        write(RETRY_WORK / "status.json", status)
        for item in plan:
            effort, seed = item["effort"], item["seed"]
            folder = DATA / effort / "landing-retry-1" / str(seed)
            if not (folder / "submission.json").exists():
                if folder.exists():
                    raise RuntimeError("Unfinished evidence retained; refusing to overwrite")
                if source_identity()["source_hash"] != identity:
                    raise RuntimeError("Frozen benchmark source changed")
                status["current"] = item
                write(RETRY_WORK / "status.json", status)
                command = [
                    str(ROOT / ".venv/bin/python"),
                    "-u",
                    str(
                        ROOT / "docs/local-model-runtime/scoring-v2-2026-10-22/diagnostic_entry.py"
                    ),
                    "eval",
                    "--controller",
                    "codex",
                    "--model",
                    MODEL,
                    "--reasoning-effort",
                    effort,
                    "--metadata",
                    str(WORK / f"{effort}.json"),
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
                with (RETRY_WORK / f"{effort}-{seed}.log").open("x") as log:
                    subprocess.run(
                        command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True
                    )
            record = read_trial(folder, effort, seed, identity)
            status["completed"].append(
                {**item, "run_id": record["run_id"], "outcome": record["outcome"]}
            )
            write(RETRY_WORK / "status.json", status)
            subprocess.run(
                [str(ROOT / ".venv/bin/python"), "examples/update_benchmark_additions.py"],
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
        write(RETRY_WORK / "status.json", status)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        write(RETRY_WORK / "failure.json", {"exception_type": type(error).__name__, "at": now()})
        raise
