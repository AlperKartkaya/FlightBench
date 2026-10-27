"""Pinned Clef-Flash conformance and one-seed serial evaluation."""

import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "docs/local-model-runtime/local-v2-lockstep-2026-10-26/clef-flash"
MODEL = ROOT / "scratch/clef-flash/model/Clef-Flash-Q4_K_M.gguf"
ARCHIVE = ROOT / "scratch/clef-flash/llama-b11429-bin-macos-arm64.tar.gz"
SERVER = next((ROOT / "scratch/clef-flash/runtime-b11429").glob("*/llama-server"))
PYTHON = ROOT / ".venv/bin/python"
ENDPOINT = "http://127.0.0.1:8012"
EXPECTED_SOURCE = None
sys.path.insert(0, str(ROOT))
from flightbench.runs import now, source_identity

EXPECTED_SOURCE = json.loads((OUT.parent / "source.json").read_text())["identity"]["source_hash"]


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def get(path):
    opener = build_opener(ProxyHandler({}))
    with opener.open(Request(ENDPOINT + path), timeout=5) as response:
        return json.load(response)


def stop(process):
    if process and process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def start(log_name, env, command):
    log = (OUT / log_name).open("w")
    process = subprocess.Popen(
        command, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
    )
    try:
        for _ in range(240):
            if process.poll() is not None:
                raise RuntimeError(f"server exited; see {log_name}")
            try:
                health = get("/health")
                if health.get("status") == "ok":
                    return process, log, health
            except OSError:
                pass
            time.sleep(1)
        raise TimeoutError("runtime readiness timed out")
    except Exception:
        stop(process)
        log.close()
        raise


OUT.mkdir(parents=True, exist_ok=True)
if any(OUT.iterdir()):
    raise FileExistsError(f"preserving existing evidence: {OUT}")
with socket.socket() as sock:
    if sock.connect_ex(("127.0.0.1", 8012)) == 0:
        raise RuntimeError("port 8012 occupied; refusing interference")
assert MODEL.stat().st_size == 6486448288
assert sha(MODEL) == "fd3e90605e8103307dca37cb5a8cdb036267e2fe3cb2d908d80a8ceb9ec0638c"
assert ARCHIVE.stat().st_size == 11971406
assert sha(ARCHIVE) == "740288ec6887be94280a5dfa25b5e23a78285cab104519e6c7e218904ee82459"
identity = source_identity()
assert identity["source_hash"] == EXPECTED_SOURCE, identity
source_archive = (
    ROOT / "docs/local-model-runtime/local-v2-lockstep-2026-10-26/benchmark-source.tar.gz"
)
write(
    "source.json",
    {
        "identity": identity,
        "benchmark_source_archive": str(source_archive.relative_to(ROOT)),
        "benchmark_source_archive_sha256": sha(source_archive),
    },
)
metadata = {
    "name": "Clef-Flash 9B Q4_K_M",
    "slug": "clef-flash-9b-q4-v2-lockstep-s42",
    "model": "clef-flash-q4",
    "provider": "Cloudflare / ggml-org / local llama.cpp",
    "source_url": "https://huggingface.co/Cloudflare/clef-flash",
    "license": "Apache-2.0",
    "model_revision": "fde727a287004204b7518dcc983fe64379776712",
    "quantized_model_source": "ggml-org/Clef-Flash-GGUF",
    "quantized_model_revision": "4a192915ef971886004b5b13294f2b4c7a7fc39d",
    "source_revision": "d81235049384534c167caea52b85a694f6103d14",
    "backend": "llama.cpp b11429 Metal; all requested layers offloaded with -ngl 99; CPU helper threads 2",
    "quantization": "Q4_K_M",
    "parameter_count": 9000000000,
    "n_ctx": 8192,
    "n_seq_max": 1,
    "controller_type": "ai",
    "local": True,
    "cost_methodology": "Local provider fee zero; hardware/electricity excluded.",
    "files": {
        MODEL.name: {"sha256": sha(MODEL), "bytes": MODEL.stat().st_size},
        ARCHIVE.name: {"sha256": sha(ARCHIVE), "bytes": ARCHIVE.stat().st_size},
    },
    "campaign": {
        "id": "local-v2-lockstep-2026-10-26",
        "model_parallelism": 1,
        "per_model_episode_jobs": 1,
        "shared_hardware": "Apple M1 Pro 16GB unified memory",
        "scenario": "easy: seed-independent physical initialization",
        "decision_hz": 2,
        "time_scale": 1.0,
        "scoring_version": "v2",
        "warmup": "One complete canonical initial-state request before the episode; retained separately.",
        "order": "Lockstep seed 42 only; dedicated fresh server after conformance; host kept awake with caffeinate -i.",
        "isolation": "Other desktop/agent activity possible; no other benchmark model jobs.",
    },
}
write("metadata.json", metadata)
env = {k: os.environ[k] for k in ("HOME", "PATH", "TMPDIR") if k in os.environ}
env.update(
    {
        "OMP_NUM_THREADS": "2",
        "VECLIB_MAXIMUM_THREADS": "2",
        "PYTHONUNBUFFERED": "1",
        "FLIGHTBENCH_SYSTEMONE_URL": ENDPOINT,
        "FLIGHTBENCH_LOCAL_METADATA": str(OUT / "metadata.json"),
    }
)
command = [
    str(SERVER),
    "-m",
    str(MODEL),
    "--host",
    "127.0.0.1",
    "--port",
    "8012",
    "--alias",
    "clef-flash-q4",
    "-ngl",
    "99",
    "-c",
    "8192",
    "-b",
    "8192",
    "-ub",
    "8192",
    "-np",
    "1",
    "-t",
    "2",
    "-tb",
    "2",
]
status = {
    "started_at": now(),
    "status": "starting",
    "command": command,
    "environment": {k: env[k] for k in ("OMP_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")},
}
write("status.json", status)
awake = subprocess.Popen(["/usr/bin/caffeinate", "-i"], start_new_session=True)
server = log = None
try:
    server, log, health = start("conformance-server.log", env, command)
    write(
        "conformance-runtime.json",
        {
            "health": health,
            "props": get("/props"),
            "process": {
                "pid": server.pid,
                "rss_kib": int(
                    subprocess.check_output(
                        ["ps", "-o", "rss=", "-p", str(server.pid)], text=True
                    ).strip()
                ),
            },
        },
    )
    subprocess.run(
        [
            str(PYTHON),
            "-m",
            "flightbench.diagnostics",
            "--states",
            "tests/fixtures/decision-states-v1.json",
            "--model",
            "clef-flash-q4",
            "--endpoint",
            ENDPOINT,
            "--repeats",
            "1",
            "--conditions",
            "Apple M1 Pro 16GB; isolated llama.cpp b11429 Metal server; -ngl99 -c8192 -b8192 -ub8192 -np1; no other model benchmark; conformance only, not accuracy",
            "--output",
            str(OUT / "conformance.json"),
        ],
        cwd=ROOT,
        env=env,
        check=True,
        timeout=600,
    )
    stop(server)
    server = None
    log.close()
    log = None
    server, log, health = start("evaluation-server.log", env, command)
    write(
        "runtime-before.json",
        {
            "health": health,
            "props": get("/props"),
            "process": {
                "pid": server.pid,
                "rss_kib": int(
                    subprocess.check_output(
                        ["ps", "-o", "rss=", "-p", str(server.pid)], text=True
                    ).strip()
                ),
            },
        },
    )
    warmup = """import json,time\nfrom pathlib import Path\nfrom flightbench.local import SystemOneController\nfrom flightbench.environment import FixedWingLandingEnv\nfrom flightbench.temporal import TelemetryHistory\ne=FixedWingLandingEnv();o,_=e.reset(seed=42);h=TelemetryHistory();h.add(o);o["temporal"]=h.features(o)\nc=SystemOneController("clef-flash-q4");t=time.perf_counter();a=c.decide(o)\nPath(OUTPUT).write_text(json.dumps({"latency_ms":(time.perf_counter()-t)*1000,"decision_info":c.last_decision,"command":a.model_dump()},indent=2,allow_nan=False)+"\\n");e.close()\n""".replace(
        "OUTPUT", repr(str(OUT / "warmup.json"))
    )
    subprocess.run([str(PYTHON), "-c", warmup], cwd=ROOT, env=env, check=True, timeout=180)
    assert source_identity()["source_hash"] == EXPECTED_SOURCE
    status["status"] = "evaluating"
    write("status.json", status)
    submission = (
        ROOT
        / "leaderboard/campaigns/2026-10-26-local-v2/submissions/clef-flash-9b-q4-v2-lockstep-s42"
    )
    with (OUT / "evaluation.log").open("w") as evaluation_log:
        subprocess.run(
            [
                str(PYTHON),
                "-m",
                "flightbench.benchmark",
                "eval",
                "--controller",
                "systemone",
                "--model",
                "clef-flash-q4",
                "--metadata",
                str(OUT / "metadata.json"),
                "--modes",
                "lockstep",
                "--seeds",
                "42",
                "--jobs",
                "1",
                "--decision-hz",
                "2",
                "--time-scale",
                "1.0",
                "--timeout",
                "120",
                "--output-dir",
                str(submission),
            ],
            cwd=ROOT,
            env=env,
            stdout=evaluation_log,
            stderr=subprocess.STDOUT,
            check=True,
        )
    subprocess.run(
        [
            str(PYTHON),
            "-m",
            "flightbench.leaderboard",
            "validate",
            str(submission / "submission.json"),
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )
    write(
        "runtime-after.json",
        {
            "health": get("/health"),
            "props": get("/props"),
            "process": {
                "pid": server.pid,
                "rss_kib": int(
                    subprocess.check_output(
                        ["ps", "-o", "rss=", "-p", str(server.pid)], text=True
                    ).strip()
                ),
            },
        },
    )
    status.update(
        {
            "status": "complete",
            "submission": str((submission / "submission.json").relative_to(ROOT)),
            "finished_at": now(),
        }
    )
    write("status.json", status)
finally:
    stop(server)
    if log:
        log.close()
    stop(awake)
