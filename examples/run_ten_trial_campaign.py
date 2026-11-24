"""Run the requested 110 easy flights, retaining attempts, provider logs and replays."""

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
from time import perf_counter, sleep, time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from examples.rescore_episode import _assert_same, replay_and_rescore
from examples.run_azure_decision_campaign import realtime_inputs, write
from flightbench.benchmark import INCOMPLETE_STATUSES
from flightbench.leaderboard import validate_submission
from flightbench.protocol import canonical_observation, command_from_action_ids
from flightbench.runs import SOURCE_FILES, now, source_identity
from flightbench.temporal import TelemetryHistory

DATA = ROOT / "leaderboard/campaigns/2026-11-15-ten-trial-easy"
EVIDENCE = ROOT / "docs/evaluations/2026-11-15-ten-trial-easy"
SEEDS = (42, 101, 202, 303, 404, 505, 606, 707, 808, 909)
GROUPS = (
    [
        (f"jev-{version}-{mode}", "jev", f"jev-{version}.0", mode)
        for version in ("1.13", "1.14")
        for mode in ("realtime", "lockstep")
    ]
    + [
        (f"{model}-low-lockstep", "codex", f"openai-codex/gpt-{model}", "lockstep")
        for model in ("6-astra", "6.1-sol", "6.1-terra", "6-luna")
    ]
    + [
        (
            "microsoft-decision-1-lockstep",
            "examples.controllers.azure_decision:AzureDecisionController",
            "Microsoft-Decision-1",
            "lockstep",
        ),
        (
            "openai-luna-decisions-lockstep",
            "examples.controllers.decision_apis:OpenAIDecisionController",
            "gpt-6-luna",
            "lockstep",
        ),
        (
            "gemini-decision-1-lockstep",
            "examples.controllers.decision_apis:GeminiDecisionController",
            "gemini-decision-1",
            "lockstep",
        ),
    ]
)
EXTRA_SOURCE = (
    Path(__file__),
    ROOT / "examples/controllers/decision_apis.py",
    ROOT / "examples/controllers/azure_decision.py",
    ROOT / "examples/rescore_episode.py",
    ROOT / "examples/run_azure_decision_campaign.py",
)


def append(path, row):
    # Payloads only: never write headers, client configuration, or credential objects.
    value = json.dumps({"at": now(), **row}, allow_nan=False)
    for name in ("TYPESAFE_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        if os.environ.get(name):
            value = value.replace(os.environ[name], "[REDACTED]")
    with path.open("a") as log:
        log.write(value + "\n")
        log.flush()
        os.fsync(log.fileno())


def codex_final_text(response):
    messages = [
        item
        for item in response["output"]
        if item["type"] == "message" and item.get("phase") in {None, "final_answer"}
    ]
    assert len(messages) == 1, "Expected one unambiguous final assistant message"
    return "".join(c["text"] for c in messages[0]["content"] if c["type"] == "output_text")


def install_logging(path, controller):
    if controller == "jev":
        from typesafe_sdk import TypeSafeClient

        original = TypeSafeClient._request

        def request(self, prepared, **kwargs):
            row = {"request": json.loads(prepared.content)}
            start = perf_counter()
            try:
                response = original(self, prepared, **kwargs)
                row.update(
                    status=response.raw_http_response.status_code,
                    response=response.raw_http_response.json(),
                )
                return response
            except Exception as error:
                row.update(
                    exception_type=type(error).__name__, status=getattr(error, "status_code", None)
                )
                raise
            finally:
                row["latency_ms"] = (perf_counter() - start) * 1000
                append(path, row)

        TypeSafeClient._request = request
    elif controller == "codex":
        from llm_openai_via_codex import CodexResponsesModel
        from openai import APIConnectionError

        original_build = CodexResponsesModel._build_kwargs
        original_event = CodexResponsesModel._handle_event
        original_client = CodexResponsesModel._get_client_kwargs

        def client_kwargs(self):
            return {**original_client(self), "timeout": 60, "max_retries": 0}

        def build(self, *args, **kwargs):
            payload = original_build(self, *args, **kwargs)
            append(path, {"event": "request", "request": payload})
            return payload

        def event(self, event, response):
            if event.type in {"response.completed", "response.failed", "error"}:
                append(path, {"event": event.type, "response": event.model_dump(mode="json")})
            result = original_event(self, event, response)
            if event.type == "response.output_text.delta":
                return None
            if event.type == "response.completed":
                return codex_final_text(event.response.model_dump(mode="json"))
            return result

        CodexResponsesModel._build_kwargs = build
        CodexResponsesModel._handle_event = event
        CodexResponsesModel._get_client_kwargs = client_kwargs
        from flightbench.controllers import CodexController

        original_decide = CodexController.decide

        def decide(self, observation):
            deadline = time() + 21600
            transport_retries = 0
            while True:
                try:
                    return original_decide(self, observation)
                except Exception as error:
                    body = getattr(error, "body", None)
                    detail = body.get("error", body) if isinstance(body, dict) else {}
                    if not isinstance(detail, dict):
                        detail = {}
                    append(
                        path,
                        {
                            "event": "controller_error",
                            "exception_type": type(error).__name__,
                            "http_status": getattr(error, "status_code", None),
                            "provider_error": {
                                key: detail[key]
                                for key in (
                                    "type",
                                    "code",
                                    "message",
                                    "resets_at",
                                    "resets_in_seconds",
                                )
                                if key in detail
                            },
                        },
                    )
                    overloaded = detail.get("code") == "server_is_overloaded"
                    if (
                        isinstance(error, APIConnectionError) or overloaded
                    ) and transport_retries < 2:
                        transport_retries += 1
                        sleep(5 if overloaded else 1)
                        continue
                    reset = detail.get("resets_at")
                    if not (
                        getattr(error, "status_code", None) == 429
                        and detail.get("type") == "usage_limit_reached"
                        and isinstance(reset, (int, float))
                    ):
                        raise
                    seconds = max(1, reset - time() + 5)
                    if time() + seconds > deadline:
                        raise
                    # Lockstep holds the same observation while the account quota resets.
                    append(path, {"event": "quota_wait", "seconds": seconds, "resets_at": reset})
                    wake_at = time() + seconds
                    while (remaining := wake_at - time()) > 0:
                        sleep(min(60, remaining))

        CodexController.decide = decide


def trial(group, seed, folder):
    from flightbench.benchmark import evaluate

    _, controller, model, mode = group
    folder.mkdir(parents=True, exist_ok=False)
    raw = folder / "provider.jsonl"
    os.environ.update(FLIGHTBENCH_AZURE_LOG=str(raw), FLIGHTBENCH_DECISION_LOG=str(raw))
    install_logging(raw, controller)
    evaluate(
        [
            "--controller",
            controller,
            "--model",
            model,
            "--reasoning-effort",
            "low",
            "--modes",
            mode,
            "--seeds",
            str(seed),
            "--scenario",
            "easy",
            "--decision-hz",
            "2",
            "--time-scale",
            "1.0",
            "--timeout",
            "21900" if controller == "codex" else "300",
            "--jobs",
            "1",
            "--output-dir",
            str(folder),
        ]
    )


def successful_responses(rows):
    responses, pending = [], None
    for row in rows:
        if pending is not None:
            assert row["request"] == pending, "Retry changed the request payload"
        if row.get("status") == 200:
            responses.append(row)
            pending = None
        else:
            assert row.get("status") in {0, 429, 500, 502, 503, 504}
            pending = row["request"]
    assert pending is None, "Unfinished request cannot count as a flight"
    return responses


def completed_codex_requests(rows):
    completed, pending, retry = [], None, False
    for row in rows:
        event = row.get("event")
        if event == "request":
            if pending is not None:
                assert retry and row["request"] == pending, "Retry changed the request payload"
            pending, retry = row["request"], False
        elif event == "controller_error":
            assert pending is not None
            retry = True
        elif event == "response.completed":
            assert pending is not None and not retry
            completed.append(pending)
            pending = None
    assert pending is None, "Unfinished request cannot count as a flight"
    return completed


def verify(folder, group, seed, identity):
    manifest = validate_submission(json.loads((folder / "submission.json").read_text()), folder)
    assert len(manifest.artifacts) == 1
    with gzip.open(folder / manifest.artifacts[0].path, "rt") as handle:
        record = json.load(handle)
    return verify_episode(record, folder, group, seed, identity)


def verify_episode(record, folder, group, seed, identity):
    """Audit raw evidence independently of the stricter leaderboard manifest format."""
    cfg = record["config"]
    assert record["source_identity"]["source_hash"] == identity["source_hash"]
    assert (cfg["controller"], cfg["model"], cfg["mode"], cfg["seed"]) == (*group[1:], seed)
    assert (cfg["scenario"], cfg["decision_hz"], cfg["time_scale"]) == ("easy", 2, 1.0)
    assert cfg["reasoning_effort"] == "low"
    if record["outcome"]["status"] in INCOMPLETE_STATUSES or record["diagnostics"]["api_errors"]:
        raise RuntimeError("Infrastructure failure retained; not a scored flight")
    raw = [json.loads(line) for line in (folder / "provider.jsonl").read_text().splitlines()]
    if group[1] == "codex":
        requests = completed_codex_requests(raw)
        states = [json.loads(r["input"][-1]["content"]) for r in requests]
        assert all(r["reasoning"] == {"effort": "low"} for r in requests)
        assert sum(r.get("event") == "response.completed" for r in raw) == len(requests)
    else:
        raw = successful_responses(raw)
        requests = [r["request"] for r in raw if "request" in r]
        states = [r.get("state", r["request"].get("state")) for r in raw if "request" in r]
        assert all(r.get("status") == 200 for r in raw)
    decisions = record["decisions"]
    assert len(states) == record["diagnostics"]["requests_started"]
    if cfg["mode"] == "realtime":
        realtime_inputs(record, [{"state": state} for state in states])
    else:
        assert len(states) == len(decisions)
        history = TelemetryHistory()
        for state, decision in zip(states, decisions, strict=True):
            observation = decision["observation"]
            history.add(observation)
            assert state == canonical_observation(
                observation | {"temporal": history.features(observation)}
            )
    for decision in decisions:
        if decision.get("applied", True):
            assert (
                command_from_action_ids(decision["decision_info"]["action_ids"]).model_dump()
                == (decision["action"])
            )
    replay = replay_and_rescore(record)
    _assert_same(replay["recorded_result"], replay["rescored_result"])
    write(folder / "replay.json", replay)
    return {
        "seed": seed,
        "run_id": record["run_id"],
        **record["outcome"],
        "diagnostics": record["diagnostics"],
        "provider_responses": len(states),
        "replay_verified": True,
        "folder": str(folder.relative_to(ROOT)),
    }


def summarize(groups):
    return [
        {
            "group": group,
            "completed": len(runs),
            "successful_landings": sum(r["success"] for r in runs),
            "highest_score": max((r["quality"] for r in runs), default=None),
        }
        for group, runs in groups.items()
    ]


def report(status):
    write(EVIDENCE / "status.json", status)
    lines = [
        "# Ten-trial easy evaluation",
        "",
        f"State: **{status['state']}**.",
        "",
        "Same ten seeds for every group: " + ", ".join(map(str, SEEDS)) + ".",
        "V2 scoring; frozen action space; 2 Hz; 1x realtime; discard-stale; Codex low only.",
        "Physical failures count. Infrastructure failures are retained, excluded, and flagged.",
        "No score-based retries. Highest score is over the completed cohort, not historical runs.",
        "",
        "| Model / mode | Completed | Successful landings | Highest score |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in summarize(status["groups"]):
        score = "pending" if row["highest_score"] is None else f"{row['highest_score']:.6f}"
        lines.append(
            f"| {row['group']} | {row['completed']}/10 | {row['successful_landings']} | {score} |"
        )
    lines += [
        "",
        "## Retained blockers / excluded attempts",
        "",
        *[
            f"- `{item['group']}` seed {item['seed']}: {item['error']} (see `{item['folder']}`)."
            for item in status["excluded"]
        ],
        "",
        "Provider request/response sidecars, full episodes, manifests and physics replays live in",
        f"`{DATA.relative_to(ROOT)}/`. Source snapshot and status are beside this report.",
        "Realtime sidecars include requests drained after termination; episode diagnostics are unchanged.",
        "Actual billing and credit coverage are not verified.",
    ]
    (EVIDENCE / "README.md").write_text("\n".join(lines) + "\n")


def main():
    global DATA, EVIDENCE, GROUPS

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", type=int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--folder", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--microsoft-decision-1-1", action="store_true")
    args = parser.parse_args()
    if args.microsoft_decision_1_1:
        campaign = "2026-11-19-microsoft-decision-1.1-easy"
        DATA = ROOT / "leaderboard/campaigns" / campaign
        EVIDENCE = ROOT / "docs/evaluations" / campaign
        GROUPS = [
            (
                "microsoft-decision-1.1-lockstep",
                "examples.controllers.azure_decision:AzureDecision11Controller",
                "Microsoft-Decision-1.1",
                "lockstep",
            )
        ]
    if args.trial is not None:
        trial(GROUPS[args.trial], args.seed, args.folder)
        return
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    with (EVIDENCE / "runner.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        identity = source_identity()
        hashes = {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in EXTRA_SOURCE
        }
        source_path = EVIDENCE / "source.json"
        if source_path.exists():
            frozen = json.loads(source_path.read_text())
            assert frozen["identity"]["source_hash"] == identity["source_hash"]
            changed = {p for p, digest in hashes.items() if frozen["extra_hashes"].get(p) != digest}
            if changed:
                assert args.resume and changed <= {
                    "examples/run_ten_trial_campaign.py",
                    "examples/controllers/decision_apis.py",
                }, "Only documented orchestration/transport changes may resume this cohort"
                revision = (
                    EVIDENCE / f"resume-source-{len(list(EVIDENCE.glob('resume-source-*.json')))}"
                )
                archive = revision.with_suffix(".tar.gz")
                with tarfile.open(archive, "x:gz") as tar:
                    for path in (*SOURCE_FILES, *EXTRA_SOURCE):
                        tar.add(path, arcname=path.relative_to(ROOT))
                write(
                    revision.with_suffix(".json"),
                    {
                        "at": now(),
                        "identity": identity,
                        "extra_hashes": hashes,
                        "changed": sorted(changed),
                        "reason": "Resume retained trials; accept identical transport retries; pace Gemini requests; separate Codex commentary from final answer; bound network/overload retries and wait for quota reset using wall-clock polling with the same pending lockstep observation. Policy, questions, scoring and physics are unchanged.",
                        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                    },
                )
        else:
            archive = EVIDENCE / "source.tar.gz"
            with tarfile.open(archive, "x:gz") as tar:
                for path in (*SOURCE_FILES, *EXTRA_SOURCE):
                    tar.add(path, arcname=path.relative_to(ROOT))
            write(
                source_path,
                {
                    "identity": identity,
                    "extra_hashes": hashes,
                    "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                },
            )
        status = {
            "state": "running",
            "started_at": now(),
            "pid": os.getpid(),
            "seeds": list(SEEDS),
            "planned_runs": len(GROUPS) * len(SEEDS),
            "groups": {g[0]: [] for g in GROUPS},
            "excluded": [],
        }
        if args.resume:
            status = json.loads((EVIDENCE / "status.json").read_text())
            status.update(state="running", pid=os.getpid(), resumed_at=now())
            status.pop("finished_at", None)
            status.pop("error", None)
        report(status)
        try:
            for index, group in enumerate(GROUPS):
                for seed in SEEDS:
                    if any(row["seed"] == seed for row in status["groups"][group[0]]):
                        continue
                    assert source_identity()["source_hash"] == identity["source_hash"]
                    assert hashes == {
                        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in EXTRA_SOURCE
                    }
                    folder = DATA / group[0] / str(seed)
                    status["current"] = {"group": group[0], "seed": seed, "started_at": now()}
                    report(status)
                    if not (folder / "submission.json").exists():
                        if folder.exists():
                            raise RuntimeError(f"Partial attempt retained at {folder}")
                        folder.parent.mkdir(parents=True, exist_ok=True)
                        with (folder.parent / f"{seed}.log").open("x") as log:
                            result = subprocess.run(
                                [
                                    sys.executable,
                                    "-u",
                                    str(Path(__file__)),
                                    *(
                                        ["--microsoft-decision-1-1"]
                                        if args.microsoft_decision_1_1
                                        else []
                                    ),
                                    "--trial",
                                    str(index),
                                    "--seed",
                                    str(seed),
                                    "--folder",
                                    str(folder),
                                ],
                                cwd=ROOT,
                                stdout=log,
                                stderr=subprocess.STDOUT,
                                timeout=None if group[1] == "codex" else 7200,
                                check=False,
                            )
                        if result.returncode:
                            status["excluded"].append(
                                {
                                    "group": group[0],
                                    "seed": seed,
                                    "error": f"runner_exit_{result.returncode}",
                                    "folder": str(folder.relative_to(ROOT)),
                                }
                            )
                            report(status)
                            break
                    try:
                        row = verify(folder, group, seed, identity)
                    except Exception as error:  # noqa: BLE001 - retain failed audits, continue other groups
                        status["excluded"].append(
                            {
                                "group": group[0],
                                "seed": seed,
                                "error": type(error).__name__,
                                "folder": str(folder.relative_to(ROOT)),
                            }
                        )
                        report(status)
                        break
                    status["groups"][group[0]].append(row)
                    print(json.dumps({"group": group[0], **row}), flush=True)
                    report(status)
            status["state"] = (
                "complete" if all(len(r) == 10 for r in status["groups"].values()) else "incomplete"
            )
        except Exception as error:
            status.update(state="blocked", error=type(error).__name__)
            raise
        finally:
            status["finished_at"] = now()
            status.pop("current", None)
            report(status)


if __name__ == "__main__":
    main()
