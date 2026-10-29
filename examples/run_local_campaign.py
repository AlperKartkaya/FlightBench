"""Resume the six-model local V2 campaign, one lockstep flight at a time."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import plistlib
import shutil
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flightbench.leaderboard import validate_submission
from flightbench.runs import source_identity

SOURCE_HASH = "sha256:ebbaf763d742e79e847f43f8f64f701ec923160f770960b0d6cecfe3c81fa128"
SCORING_HASH = "82684d68cfb2dc37bd08ee8a1e0072d88d31a3190483eb89b39e523a0b8a7b80"
OLD = ROOT / "leaderboard/campaigns/2026-10-26-local-v2/submissions"
NEW = ROOT / "leaderboard/campaigns/2026-10-28-local-v2/submissions"
WORK = ROOT / "scratch/local-v2-three-seeds-2026-10-28"
PYTHON = ROOT / ".venv/bin/python"


@dataclass(frozen=True)
class Model:
    name: str
    old_slug: str
    port: int
    health_path: str
    command: tuple[str, ...]
    environment: dict[str, str]


def _models() -> tuple[Model, ...]:
    runtime = ROOT / "docs/local-model-runtime/local-v2-lockstep-2026-10-26"
    rows = {row["model"]: row for row in json.loads((runtime / "status.json").read_text())}
    clef = json.loads((runtime / "clef-flash/status.json").read_text())
    definitions = (
        ("kev", "kev-0.8b-v1-v2-lockstep-s42", 11436, "/v1/models", rows["kev"]),
        (
            "openthai",
            "openthai-v0.3-q8-v2-lockstep-s42",
            11435,
            "/api/version",
            rows["openthai"],
        ),
        ("decider", "decider-2b-v11-q4-v2-lockstep-s42", 11439, "/", rows["decider"]),
        ("von", "von-1.3-v2-lockstep-s42", 11437, "/health", rows["von"]),
        (
            "nimble",
            "nimble-9b-q4-v2-lockstep-s42",
            11435,
            "/api/version",
            rows["nimble"],
        ),
        ("clef", "clef-flash-9b-q4-v2-lockstep-s42", 8012, "/health", clef),
    )
    return tuple(
        Model(name, slug, port, health, tuple(row["command"]), row.get("environment", {}))
        for name, slug, port, health, row in definitions
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def _remember_success(status: dict, model: str, seed: int, outcome: dict) -> None:
    item = {"model": model, "seed": seed, "outcome": outcome}
    if outcome.get("success") and item not in status["successful"]:
        status["successful"].append(item)


def _completion(interrupted: bool, failed: bool) -> tuple[str, int]:
    if interrupted:
        return "interrupted", 130
    return ("complete_with_errors", 1) if failed else ("complete", 0)


def _record(path: Path) -> dict:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as source:
        return json.load(source)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_trial(path: Path, seed: int, expected_model: str) -> dict:
    """Return the sole episode after enforcing the publishable campaign contract."""
    submission = validate_submission(json.loads(path.read_text()), path.parent)
    if submission.flightbench.source_hash != SOURCE_HASH:
        raise ValueError(f"unexpected source hash: {path}")
    evaluation = submission.evaluation
    if (
        evaluation.seeds != [seed]
        or evaluation.modes != ["lockstep"]
        or evaluation.scoring_version != "v2"
        or evaluation.scoring_config_sha256 != SCORING_HASH
    ):
        raise ValueError(f"unexpected evaluation contract: {path}")
    if len(submission.artifacts) != 1 or len(submission.runs) != 1:
        raise ValueError(f"expected one run and artifact: {path}")
    episode = _record(path.parent / submission.artifacts[0].path)
    config = episode.get("config", {})
    if config.get("seed") != seed or config.get("mode") != "lockstep":
        raise ValueError(f"episode seed/mode mismatch: {path}")
    if episode.get("diagnostics", {}).get("api_errors") != 0:
        raise ValueError(f"controller/API errors are not publishable: {path}")
    if (
        not submission.controller.local
        or submission.controller.model != expected_model
        or config.get("model") != expected_model
        or config.get("controller") != "systemone"
    ):
        raise ValueError(f"wrong local controller/model: {path}")
    if episode.get("outcome", {}).get("status") not in {
        "landed",
        "runway_excursion",
        "out_of_bounds",
        "nose_first_contact",
        "crash",
    }:
        raise ValueError(f"episode did not reach a physical terminal outcome: {path}")
    if episode.get("diagnostics", {}).get("interventions", {}).get("applied", 0) < 1:
        raise ValueError(f"episode has no applied actuator commands: {path}")
    return episode


def _metadata(model: Model) -> tuple[dict, str]:
    path = OLD / model.old_slug / "submission.json"
    controller = json.loads(path.read_text())["controller"]
    validate_trial(path, 42, controller["model"])
    metadata = {**controller.pop("metadata", {}), **controller}
    metadata["controller_type"] = metadata.pop("type")
    metadata["slug"] = model.old_slug.removesuffix("-s42")
    metadata["campaign"] = {
        "id": "local-v2-three-seeds-2026-10-28",
        "seeds": [42, 101, 202],
        "model_parallelism": 1,
        "per_model_episode_jobs": 1,
        "scenario": "easy: seed-independent physical initialization",
        "decision_hz": 2,
        "time_scale": 1.0,
        "scoring_version": "v2",
        "order": "One local model server and one lockstep episode at a time.",
        "seed_42": "Reused from the validated October 26 campaign; not rerun.",
    }
    return metadata, metadata["model"]


def _verify_model(model: Model, metadata: dict) -> None:
    """Verify the pinned local files already named by the retained controller manifest."""
    if model.name in {"openthai", "nimble"}:
        relative = (
            "iapp/openthai-systemone/0.8b-q8_0"
            if model.name == "openthai"
            else "library/nimble/9b-q4_K_M"
        )
        store = Path.home() / ".ollama/models"
        manifest = store / "manifests/registry.ollama.ai" / relative
        if _sha256(manifest) != metadata["model_manifest_sha256"]:
            raise ValueError(f"unpinned Ollama manifest: {manifest}")
        for layer in json.loads(manifest.read_text())["layers"]:
            blob = store / "blobs" / layer["digest"].replace(":", "-")
            if _sha256(blob) != layer["digest"].split(":", 1)[1]:
                raise ValueError(f"unpinned Ollama layer: {blob}")
        return
    roots = {
        "kev": ROOT / "scratch/huggingface/hub",
        "decider": ROOT / "scratch/decider-runtime/model",
        "von": ROOT / "scratch/von-runtime/model",
        "clef": ROOT / "scratch/clef-flash",
    }
    root = roots[model.name]
    for filename, expected in metadata.get("files", {}).items():
        matches = [path for path in root.rglob(filename) if path.is_file()]
        wanted = expected["sha256"].removeprefix("sha256:")
        if not any(_sha256(path) == wanted for path in matches):
            raise ValueError(f"pinned model file missing or changed: {filename}")


def _request(url: str) -> dict:
    opener = build_opener(ProxyHandler({}))
    with opener.open(Request(url), timeout=5) as response:
        return json.load(response)


def _port_free(port: int) -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


def _stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def _fresh_work(model: Model, seed: int) -> Path:
    current = WORK / "current" / model.name / str(seed)
    if current.exists():
        archive = WORK / "interrupted" / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{model.name}-{seed}"
        archive.parent.mkdir(parents=True, exist_ok=True)
        current.replace(archive)
    current.mkdir(parents=True)
    return current


def _published(model: Model, seed: int) -> Path:
    return NEW / model.old_slug.removesuffix("-s42") / "trials" / str(seed) / "submission.json"


def _publish(source: Path, model: Model, seed: int, model_name: str) -> Path:
    manifest = source / "submission.json"
    validate_trial(manifest, seed, model_name)
    data = json.loads(manifest.read_text())
    artifacts = [source / artifact["path"] for artifact in data["artifacts"]]
    if any(path.suffix != ".gz" for path in artifacts):
        raise ValueError("only compressed full episode records are published")
    target = _published(model, seed).parent
    if target.exists():
        archive = (
            WORK
            / "interrupted"
            / f"{datetime.now(UTC):%Y%m%dT%H%M%S.%fZ}-{model.name}-{seed}-published"
        )
        archive.parent.mkdir(parents=True, exist_ok=True)
        target.replace(archive)
    target.mkdir(parents=True)
    for artifact_path in artifacts:
        shutil.copy2(artifact_path, target / artifact_path.name)
    shutil.copy2(manifest, target / "submission.json")
    validate_trial(target / "submission.json", seed, model_name)
    return target / "submission.json"


def _warmup(env: dict[str, str], model_name: str, seed: int, output: Path, stopped) -> bool:
    script = (
        """import json,time
from pathlib import Path
from flightbench.local import SystemOneController
from flightbench.environment import FixedWingLandingEnv
from flightbench.temporal import TelemetryHistory
e=FixedWingLandingEnv();o,_=e.reset(seed=SEED);h=TelemetryHistory();h.add(o);o['temporal']=h.features(o)
c=SystemOneController(MODEL);t=time.perf_counter();a=c.decide(o)
Path(OUTPUT).write_text(json.dumps({'latency_ms':(time.perf_counter()-t)*1000,'decision_info':c.last_decision,'command':a.model_dump()},indent=2,allow_nan=False)+'\\n');e.close()
""".replace("SEED", str(seed))
        .replace("MODEL", repr(model_name))
        .replace("OUTPUT", repr(str(output)))
    )
    process = subprocess.Popen(
        [str(PYTHON), "-c", script], cwd=ROOT, env=env, start_new_session=True
    )
    deadline = time.monotonic() + 300
    try:
        while process.poll() is None:
            if stopped():
                _stop(process)
                return False
            if time.monotonic() >= deadline:
                _stop(process)
                raise TimeoutError("model warmup timed out")
            time.sleep(1)
        if process.returncode:
            raise RuntimeError("model warmup failed")
        return True
    finally:
        _stop(process)


def run_campaign() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    lock = WORK / "runner.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"campaign already active or needs stale-lock review: {lock}") from exc
    os.write(descriptor, str(os.getpid()).encode())
    os.close(descriptor)
    status_path = WORK / "status.json"
    status = {"started_at": _now(), "state": "running", "models": {}, "successful": []}
    base_env = {key: os.environ[key] for key in ("HOME", "PATH", "TMPDIR") if key in os.environ}
    base_env.update(
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        TOKENIZERS_PARALLELISM="false",
        OMP_NUM_THREADS="2",
        MKL_NUM_THREADS="2",
        VECLIB_MAXIMUM_THREADS="2",
        PYTHONUNBUFFERED="1",
    )
    interrupted = False

    def stop_requested(_signum, _frame):
        nonlocal interrupted
        interrupted = True

    previous = {sig: signal.signal(sig, stop_requested) for sig in (signal.SIGINT, signal.SIGTERM)}
    awake = subprocess.Popen(
        ["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())], start_new_session=True
    )
    _write(status_path, status)
    try:
        for model in _models():
            metadata, model_name = _metadata(model)
            old_path = OLD / model.old_slug / "submission.json"
            old_episode = validate_trial(old_path, 42, model_name)
            row = status["models"].setdefault(
                model.name,
                {
                    "seed_42": {
                        "state": "reused",
                        "submission": str(old_path.relative_to(ROOT)),
                        "outcome": old_episode["outcome"],
                    },
                    "seeds": {},
                },
            )
            _remember_success(status, model.name, 42, old_episode["outcome"])
            pending = []
            for seed in (101, 202):
                published = _published(model, seed)
                try:
                    episode = validate_trial(published, seed, model_name)
                except (FileNotFoundError, ValueError):
                    pending.append(seed)
                else:
                    row["seeds"][str(seed)] = {
                        "state": "complete",
                        "submission": str(published.relative_to(ROOT)),
                        "outcome": episode["outcome"],
                    }
                    _remember_success(status, model.name, seed, episode["outcome"])
            if not pending:
                continue
            if interrupted:
                break
            _verify_model(model, metadata)
            if not _port_free(model.port):
                raise RuntimeError(f"port {model.port} occupied; refusing interference")
            env = base_env | model.environment
            endpoint = f"http://127.0.0.1:{model.port}"
            metadata_path = WORK / "metadata" / f"{model.name}.json"
            _write(metadata_path, metadata)
            env |= {
                "FLIGHTBENCH_SYSTEMONE_URL": endpoint,
                "FLIGHTBENCH_LOCAL_METADATA": str(metadata_path),
            }
            server = None
            server_log_path = WORK / "logs" / f"{model.name}-server.log"
            server_log_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with server_log_path.open("a") as server_log:
                    server = subprocess.Popen(
                        model.command,
                        cwd=ROOT,
                        env=env,
                        stdout=server_log,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                    for _ in range(300):
                        if interrupted:
                            break
                        if server.poll() is not None:
                            raise RuntimeError(f"{model.name} server exited before readiness")
                        try:
                            _request(endpoint + model.health_path)
                            break
                        except OSError:
                            time.sleep(1)
                    else:
                        raise TimeoutError(f"{model.name} server readiness timed out")
                    for seed in pending:
                        if interrupted:
                            break
                        if source_identity()["source_hash"] != SOURCE_HASH:
                            raise RuntimeError("benchmark source changed before flight")
                        work = _fresh_work(model, seed)
                        if not _warmup(
                            env, model_name, seed, work / "warmup.json", lambda: interrupted
                        ):
                            break
                        row["seeds"][str(seed)] = {"state": "evaluating", "started_at": _now()}
                        _write(status_path, status)
                        eval_log = work / "evaluation.log"
                        with eval_log.open("w") as output:
                            evaluation = subprocess.Popen(
                                [
                                    str(PYTHON),
                                    "-m",
                                    "flightbench.benchmark",
                                    "eval",
                                    "--controller",
                                    "systemone",
                                    "--model",
                                    model_name,
                                    "--metadata",
                                    str(metadata_path),
                                    "--modes",
                                    "lockstep",
                                    "--seeds",
                                    str(seed),
                                    "--jobs",
                                    "1",
                                    "--decision-hz",
                                    "2",
                                    "--time-scale",
                                    "1.0",
                                    "--timeout",
                                    "120",
                                    "--output-dir",
                                    str(work / "export"),
                                ],
                                cwd=ROOT,
                                env=env,
                                stdout=output,
                                stderr=subprocess.STDOUT,
                                start_new_session=True,
                            )
                            while evaluation.poll() is None and not interrupted:
                                time.sleep(1)
                            if interrupted:
                                _stop(evaluation)
                        if interrupted:
                            break
                        if evaluation.returncode:
                            raise RuntimeError(f"{model.name} seed{seed} evaluation failed")
                        published = _publish(work / "export", model, seed, model_name)
                        episode = validate_trial(published, seed, model_name)
                        row["seeds"][str(seed)] = {
                            "state": "complete",
                            "finished_at": _now(),
                            "submission": str(published.relative_to(ROOT)),
                            "outcome": episode["outcome"],
                        }
                        _remember_success(status, model.name, seed, episode["outcome"])
                        _write(status_path, status)
            except Exception as exc:  # noqa: BLE001 - preserve failure and continue the queue.
                row["error"] = f"{type(exc).__name__}: {exc}"
                row["failed_at"] = _now()
                _write(status_path, status)
            finally:
                _stop(server)
            if interrupted:
                break
        failed = any("error" in row for row in status["models"].values())
        status["state"], exit_code = _completion(interrupted, failed)
        status["finished_at"] = _now()
        _write(status_path, status)
        return exit_code
    except BaseException as exc:
        status.update(
            state="failed",
            finished_at=_now(),
            fatal_error=f"{type(exc).__name__}: {exc}",
        )
        _write(status_path, status)
        raise
    finally:
        _stop(awake)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        lock.unlink(missing_ok=True)


def background_job() -> dict:
    return {
        "Label": "com.flightbench.local-v2-20261028",
        "ProgramArguments": [str(PYTHON), str(Path(__file__).resolve())],
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": True,
        "KeepAlive": False,
        "ExitTimeOut": 20,
        "StandardOutPath": str(WORK / "runner.stdout.log"),
        "StandardErrorPath": str(WORK / "runner.stderr.log"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--background", action="store_true", help="Run once under macOS launchd")
    args = parser.parse_args(argv)
    if args.background:
        WORK.mkdir(parents=True, exist_ok=True)
        path = WORK / "runner.plist"
        path.write_bytes(plistlib.dumps(background_job()))
        subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(path)], check=True)
        return 0
    return run_campaign()


if __name__ == "__main__":
    raise SystemExit(main())
