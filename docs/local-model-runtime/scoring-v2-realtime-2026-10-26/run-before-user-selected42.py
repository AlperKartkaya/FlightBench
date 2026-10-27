"""Run the dated realtime Jev trials, then retry Luna high until one lands."""

import gzip
import hashlib
import json
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from flightbench.leaderboard import build_submission, validate_submission
from flightbench.runs import SOURCE_FILES, now, source_identity

OUT = Path(__file__).resolve().parent
DATA = ROOT / "leaderboard/campaigns/2026-10-26-realtime/submissions"
FAILURES = ROOT / "leaderboard/campaigns/2026-10-26-realtime/failed-attempts"
IDENTITY = source_identity()
INFRA_STATUSES = {"controller_timeout", "controller_error", "interrupted", "error"}


def freeze_source():
    archive = OUT / "benchmark-source.tar.gz"
    source = OUT / "source.json"
    if archive.exists():
        frozen = json.loads(source.read_text())
        assert IDENTITY["source_hash"] == frozen["identity"]["source_hash"]
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == frozen["archive_sha256"]
        return
    with tarfile.open(archive, "x:gz") as tar:
        for path in SOURCE_FILES:
            if path.is_file():
                tar.add(path, arcname=path.relative_to(ROOT))
        tar.add(__file__, arcname="campaign-runner.py")
        tar.add(OUT / "diagnostic_entry.py", arcname="diagnostic_entry.py")
    source.write_text(
        json.dumps(
            {
                "identity": IDENTITY,
                "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            },
            indent=2,
        )
        + "\n"
    )


def read_trial(trial):
    submission = validate_submission(json.loads((trial / "submission.json").read_text()), trial)
    assert len(submission.artifacts) == 1
    artifact = trial / submission.artifacts[0].path
    record = json.loads(
        gzip.decompress(artifact.read_bytes())
        if artifact.suffix == ".gz"
        else artifact.read_bytes()
    )
    assert record["source_identity"]["source_hash"] == IDENTITY["source_hash"]
    assert record["config"]["scoring_version"] == "v2"
    return record, artifact


def metadata(slug, model, mode, seeds, selection):
    provider = "TypeSafe" if model.startswith("jev-") else "OpenAI"
    result = {
        "name": model.split("/")[-1] + (" high" if "luna" in model else " realtime"),
        "slug": slug,
        "model": model,
        "controller_type": "ai",
        "provider": provider,
        "source_url": "https://docs.typesafe.ai/models"
        if provider == "TypeSafe"
        else "https://developers.openai.com/api/docs/models/gpt-6-luna",
        "license": "proprietary hosted API",
        "local": False,
        "pricing_date": "2026-10-26",
        "cost_methodology": "Selected-flight actual token usage at dated Standard short-context API-equivalent rates; not subscription billing. Jev $0.042/M input, output free.",
        "campaign": {
            "id": "2026-10-26-realtime",
            "scoring_version": "v2",
            "seeds": seeds,
            "model_parallelism": 1,
            "per_model_episode_jobs": 1,
            "decision_hz": 2,
            "time_scale": 1.0,
            "request_timeout_s": 300,
            "scenario": "easy: repeated physical initialization",
            "selection": selection,
            "provider_hardware": "undisclosed remote",
            "warmup": "none",
            "response_policy": "apply-on-arrival" if mode == "realtime" else "lockstep",
        },
    }
    if "luna" in model:
        result["reasoning_effort"] = "high"
    return result


def run_trial(controller, model, mode, seed, slug, effort=None):
    folder = DATA / slug
    trial = folder / "trials" / str(seed)
    if (trial / "submission.json").exists():
        record, artifact = read_trial(trial)
        if record["outcome"]["status"] not in INFRA_STATUSES:
            return record, artifact
        stamp = now().replace(":", "").replace("-", "").replace("+", "-")
        target = FAILURES / f"{slug}-{seed}-{stamp}"
        target.parent.mkdir(parents=True, exist_ok=True)
        trial.rename(target)
    assert not trial.exists()
    trial.parent.mkdir(parents=True, exist_ok=True)
    meta = folder / "metadata.json"
    command = [
        str(ROOT / ".venv/bin/python"),
        "-u",
        str(OUT / "diagnostic_entry.py"),
        "eval",
        "--controller",
        controller,
        "--model",
        model,
        "--metadata",
        str(meta),
        "--modes",
        mode,
        "--seeds",
        str(seed),
        "--jobs",
        "1",
        "--decision-hz",
        "2",
        "--time-scale",
        "1.0",
        "--realtime-response-policy",
        "apply-on-arrival",
        "--timeout",
        "300",
        "--output-dir",
        str(trial),
    ]
    if effort:
        command += ["--reasoning-effort", effort]
    status_path = OUT / "status.json"
    status = json.loads(status_path.read_text()) if status_path.exists() else []
    entry = {
        "slug": slug,
        "model": model,
        "mode": mode,
        "effort": effort,
        "seed": seed,
        "started_at": now(),
        "command": command,
        "status": "running",
    }
    status.append(entry)
    status_path.write_text(json.dumps(status, indent=2) + "\n")
    with (OUT / f"{slug}-{seed}.log").open("a") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
        exported_at = None
        while process.poll() is None:
            if (trial / "submission.json").exists():
                exported_at = exported_at or time.monotonic()
                if time.monotonic() - exported_at > 15:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    entry["cleanup"] = (
                        "terminated already-exported process with residual provider work"
                    )
                    break
            time.sleep(2)
    entry.update(exit_code=process.returncode, finished_at=now())
    if not (trial / "submission.json").exists():
        entry["status"] = "export_failed"
        status_path.write_text(json.dumps(status, indent=2) + "\n")
        raise RuntimeError(f"Trial export failed: {slug} seed {seed}; inspect sanitized log")
    record, artifact = read_trial(trial)
    if mode == "realtime":
        assert record["config"]["mode"] == "realtime"
        assert record["config"]["realtime_response_policy"] == "apply-on-arrival"
    if effort:
        assert record["config"]["reasoning_effort"] == effort
    entry.update(
        status="recorded",
        outcome=record["outcome"],
        applied=record["diagnostics"]["interventions"]["applied"],
    )
    status_path.write_text(json.dumps(status, indent=2) + "\n")
    print(slug, seed, record["outcome"], flush=True)
    if record["outcome"]["status"] in INFRA_STATUSES:
        raise RuntimeError(f"Infrastructure failure: {slug} seed {seed}; inspect sanitized log")
    return record, artifact


def publish(slug, model, mode, seeds, selection, effort=None):
    folder = DATA / slug
    folder.mkdir(parents=True, exist_ok=True)
    meta = metadata(slug, model, mode, seeds, selection)
    (folder / "metadata.json").write_text(json.dumps(meta, indent=2) + "\n")
    records, artifacts = zip(
        *(
            run_trial(
                "jev" if model.startswith("jev-") else "codex", model, mode, seed, slug, effort
            )
            for seed in seeds
        ),
        strict=True,
    )
    output = folder / "submission.json"
    output.unlink(missing_ok=True)
    payload = build_submission(records, meta, artifacts, output)
    validate_submission(payload, folder)
    return records


freeze_source()
for jev_model in ("jev-1.13.0", "jev-1.14.0"):
    publish(
        jev_model.replace(".", "-") + "-realtime",
        jev_model,
        "realtime",
        [42, 101, 202],
        "highest score of three completed realtime trials; lower seed breaks ties",
    )

luna_slug = "gpt-6-luna-high-landing-retry"
luna_model = "openai-codex/gpt-6-luna"
luna_seeds = [42, 101, 202]
folder = DATA / luna_slug
folder.mkdir(parents=True, exist_ok=True)
selection = "best of three successful replacements; each original seed retried until landing; all failed attempts archived (not best of three attempts)"
(folder / "metadata.json").write_text(
    json.dumps(metadata(luna_slug, luna_model, "lockstep", luna_seeds, selection), indent=2) + "\n"
)
for seed in luna_seeds:
    while True:
        record, _ = run_trial("codex", luna_model, "lockstep", seed, luna_slug, "high")
        if record["outcome"]["success"]:
            break
        stamp = now().replace(":", "").replace("-", "").replace("+", "-")
        target = FAILURES / f"{luna_slug}-{seed}-{stamp}-completed"
        target.parent.mkdir(parents=True, exist_ok=True)
        (folder / "trials" / str(seed)).rename(target)
publish(luna_slug, luna_model, "lockstep", luna_seeds, selection, "high")
print("CAMPAIGN COMPLETE", flush=True)
