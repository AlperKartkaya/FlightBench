import gzip
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

from flightbench import controllers
from flightbench.leaderboard import (
    Submission,
    build_leaderboard,
    build_submission,
    validate_submission,
)
from flightbench.protocol import ACTION_SPACE_SHA256, ACTION_SPACE_VERSION, BENCHMARK_PROTOCOL


def episode(run_id: str, mode: str, seed: int, score: float, *, success=False, cost=None):
    return {
        "schema_version": 1,
        "run_id": run_id,
        "config": {
            "controller": "example",
            "controller_metadata": {"controller_type": "ai"},
            "protocol_participant": True,
            "model": "example-1",
            "scenario": "easy",
            "mode": mode,
            "seed": seed,
            "decision_hz": 2,
            "time_scale": 1.0,
            "benchmark_protocol": BENCHMARK_PROTOCOL,
            "action_space_version": ACTION_SPACE_VERSION,
            "action_space_sha256": ACTION_SPACE_SHA256,
        },
        "source_identity": {
            "source_hash": "sha256:" + "a" * 64,
            "git_commit": "b" * 40,
        },
        "outcome": {
            "success": success,
            "quality": score,
            "status": "landed" if success else "runway_excursion",
        },
        "diagnostics": {
            "calls": 2,
            "decision_count": 2,
            "duration_s": 1.0,
            "mean_latency_ms": 15.0,
            "late_decisions": int(mode == "realtime"),
            "stale_decisions": 0,
            "api_errors": 0,
            "requests_started": 2,
            "requests_completed": 2,
            "requests_cancel_requested": 0,
            "requests_cancelled_before_start": 0,
            "requests_outstanding": 0,
            "residual_work": False,
            "usage_unknown_requests": 0,
            "cost_usd": cost,
        },
        "final_state": {"observation": {"time_s": 1.0}},
        "decisions": [
            {
                "latency_ms": latency,
                "action": {"aileron": -0.15, "elevator": 0.15, "rudder": 0.09, "throttle": 0.5},
                "decision_info": {
                    "action_ids": {"aileron": "3", "elevator": "7", "rudder": "3", "throttle": "3"},
                    "command": {
                        "aileron": -0.15,
                        "elevator": 0.15,
                        "rudder": 0.09,
                        "throttle": 0.5,
                    },
                },
            }
            for latency in (10.0, 600.0 if mode == "realtime" else 20.0)
        ],
    }


METADATA = {
    "name": "Example model",
    "type": "ai",
    "provider": "Example Org",
    "model": "example-1",
    "source_url": "https://example.test/model",
    "license": "Apache-2.0",
    "local": True,
    "cost_kind": "local_provider_fee",
}


def write_records(tmp_path: Path, episodes: list[dict]) -> list[Path]:
    paths = []
    for item in episodes:
        path = tmp_path / f"{item['run_id']}.json"
        path.write_text(json.dumps(item))
        paths.append(path)
    return paths


def test_build_submission_copies_complete_evidence_and_calculates_metrics(tmp_path):
    episodes = [
        episode("lock-1", "lockstep", 42, 49, cost=0.0),
        episode("real-1", "realtime", 42, 61, success=True, cost=0.0),
    ]
    output = tmp_path / "submission" / "submission.json"

    payload = build_submission(episodes, METADATA, write_records(tmp_path, episodes), output)
    validated = validate_submission(payload, output.parent)

    assert validated.results["realtime"].success_rate == 1
    assert validated.results["realtime"].p50_latency_ms == 10
    assert validated.results["realtime"].p95_latency_ms == 600
    assert validated.results["realtime"].deadline_miss_rate == 0.5
    assert validated.results["realtime"].total_cost_usd == 0
    assert validated.evaluation.realtime_response_policy == "discard-stale"
    assert {artifact.path for artifact in validated.artifacts} == {
        "evidence/lock-1.json.gz",
        "evidence/real-1.json.gz",
    }
    assert all((output.parent / artifact.path).is_file() for artifact in validated.artifacts)


def test_build_submission_compares_json_normalized_episode_to_evidence(tmp_path):
    record = episode("tuple-run", "lockstep", 42, 49)
    record["final_state"]["position"] = (1.0, 2.0, 3.0)
    path = tmp_path / "tuple-run.json"
    path.write_text(json.dumps(record))

    payload = build_submission([record], METADATA, [path])

    assert payload["runs"][0]["run_id"] == "tuple-run"


def test_validation_rejects_tampered_evidence_and_fake_verified_status(tmp_path):
    episodes = [episode("run-1", "lockstep", 7, 40)]
    output = tmp_path / "entry" / "submission.json"
    payload = build_submission(episodes, METADATA, write_records(tmp_path, episodes), output)
    artifact = output.parent / payload["artifacts"][0]["path"]
    artifact.write_bytes(artifact.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="hash or size mismatch"):
        validate_submission(payload, output.parent)

    payload["verification"] = {"status": "verified", "method": "self-reported"}
    with pytest.raises(ValueError, match="community"):
        Submission.model_validate(payload)


def test_validation_recomputes_metrics_from_evidence(tmp_path):
    episodes = [episode("run-1", "lockstep", 7, 40)]
    output = tmp_path / "entry" / "submission.json"
    payload = build_submission(episodes, METADATA, write_records(tmp_path, episodes), output)
    payload["results"]["lockstep"]["mean_score"] = 99.0

    with pytest.raises(ValueError, match="metrics do not match evidence"):
        validate_submission(payload, output.parent)


@pytest.mark.parametrize(
    "field,value",
    [
        ("decision_hz", 5),
        ("scenario", "medium"),
        ("time_scale_by_mode", {"lockstep": 1.0, "realtime": 0.5}),
        ("realtime_response_policy", "apply-on-arrival"),
    ],
)
def test_validation_binds_evaluation_to_evidence(tmp_path, field, value):
    records = [
        episode("lock", "lockstep", 7, 40),
        episode("real", "realtime", 7, 40),
    ]
    output = tmp_path / "entry" / "submission.json"
    payload = build_submission(records, METADATA, write_records(tmp_path, records), output)
    payload["evaluation"][field] = value

    with pytest.raises(ValueError, match="evaluation config"):
        validate_submission(payload, output.parent)


@pytest.mark.parametrize(
    "field,value",
    [
        ("calls", 3),
        ("decision_count", 2),
        ("api_errors", 1),
        ("stale_decisions", 0),
        ("late_decisions", 0),
        ("duration_s", 2.0),
    ],
)
def test_validation_rejects_diagnostics_inconsistent_with_raw_evidence(tmp_path, field, value):
    record = episode("real", "realtime", 7, 40)
    record["decisions"][0].update(applied=False, discard_reason="stale_observation")
    record["diagnostics"].update(decision_count=1, stale_decisions=1)
    output = tmp_path / "entry" / "submission.json"
    payload = build_submission([record], METADATA, write_records(tmp_path, [record]), output)
    artifact = output.parent / payload["artifacts"][0]["path"]
    evidence = json.loads(gzip.decompress(artifact.read_bytes()))
    evidence["diagnostics"][field] = value
    raw = gzip.compress(json.dumps(evidence).encode(), mtime=0)
    artifact.write_bytes(raw)
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    payload["artifacts"][0].update(bytes=len(raw), sha256=digest)
    payload["runs"][0]["artifact_sha256"] = digest

    with pytest.raises(ValueError, match=f"raw decisions: {field}"):
        validate_submission(payload, output.parent)


@pytest.mark.parametrize("missing", ["decisions", "duration"])
def test_build_rejects_current_evidence_without_raw_fields(tmp_path, missing):
    record = episode("incomplete", "lockstep", 7, 40)
    if missing == "decisions":
        del record["decisions"]
    else:
        del record["final_state"]["observation"]["time_s"]

    with pytest.raises(ValueError, match="current v1 evidence"):
        build_submission([record], METADATA, write_records(tmp_path, [record]))


@pytest.mark.parametrize(
    "updates,error",
    [
        ({"requests_completed": 3}, "internally inconsistent"),
        (
            {
                "requests_completed": 1,
                "requests_cancel_requested": 1,
                "requests_outstanding": 1,
            },
            "residual_work",
        ),
        ({"usage_unknown_requests": 1}, "unknown usage"),
    ],
)
def test_build_rejects_inconsistent_request_accounting(tmp_path, updates, error):
    record = episode("bad-accounting", "lockstep", 7, 40)
    record["diagnostics"].update(updates)

    with pytest.raises(ValueError, match=error):
        build_submission([record], METADATA, write_records(tmp_path, [record]))


def _builtin_controller(name):
    ids = {"aileron": "3", "elevator": "7", "rudder": "3", "throttle": "3"}
    if name == "codex":
        controller = object.__new__(controllers.CodexController)
        controller.model_id = "openai-codex/test"
        response = SimpleNamespace(text=lambda: json.dumps(ids), response_json={})
        controller._model = SimpleNamespace(prompt=lambda *args, **kwargs: response)
        return controller, controller.model_id
    controller = object.__new__(controllers.JevController)
    controller._model = controllers.JEV_MODEL
    controller._retry = None
    controller._questions = {
        axis: SimpleNamespace(
            instructions=text,
            criteria={
                str(index): criterion
                for index, criterion in enumerate(controllers.JEV_CRITERIA[axis])
            },
        )
        for axis, text in controllers.JEV_INSTRUCTIONS.items()
    }
    controller._near_ground_elevator = controller._questions["elevator"]
    choices = {
        axis: SimpleNamespace(choice=choice, confidence=1.0, probabilities={choice: 1.0})
        for axis, choice in ids.items()
    }
    controller._client = SimpleNamespace(
        system_one=lambda **kwargs: SimpleNamespace(model=kwargs["model"], choices=choices)
    )
    return controller, controller._model


@pytest.mark.parametrize("name", ["codex", "jev"])
def test_builtin_decision_exports_through_submission_in_both_modes(tmp_path, name):
    controller, model = _builtin_controller(name)
    command = controller.decide(
        {
            "runway": {
                "cross_track_error_m": 0,
                "heading_error_deg": 0,
                "glideslope_error_deg": 0,
            },
            "flight": {
                "roll_deg": 0,
                "pitch_deg": 2,
                "vertical_speed_mps": -2,
                "beta_deg": 0,
                "airspeed_mps": 30,
            },
        }
    ).model_dump()
    records = [episode(f"{name}-{mode}", mode, 7, 40) for mode in ("lockstep", "realtime")]
    for record in records:
        record["config"].update(controller=name, model=model)
        record["diagnostics"].update(
            calls=1,
            decision_count=1,
            late_decisions=0,
            requests_started=1,
            requests_completed=1,
        )
        record["decisions"] = [
            {"latency_ms": 10.0, "action": command, "decision_info": controller.last_decision}
        ]
    stale = records[1]
    stale["diagnostics"].update(decision_count=0, stale_decisions=1)
    stale["decisions"][0].update(
        applied=False,
        discard_reason="stale_observation",
        action={"aileron": -0.15, "elevator": 0.17, "rudder": 0.09, "throttle": 0.5},
    )
    metadata = {
        **METADATA,
        "name": name.title(),
        "model": model,
        "local": False,
        "cost_kind": "unknown",
    }
    output = tmp_path / name / "submission.json"

    payload = build_submission(records, metadata, write_records(tmp_path, records), output)

    assert validate_submission(payload, output.parent).evaluation.modes == ["lockstep", "realtime"]


def test_controller_aliases_and_ollama_audit_metadata_are_preserved(tmp_path):
    episodes = [episode("run-1", "lockstep", 7, 40)]
    metadata = {
        **METADATA,
        "controller_type": METADATA["type"],
        "model_digest": "sha256:ollama",
        "generation_options": {"temperature": 0},
    }
    del metadata["type"]

    payload = build_submission(episodes, metadata, write_records(tmp_path, episodes))

    assert payload["controller"]["type"] == "ai"
    assert payload["controller"]["metadata"]["model_digest"] == "sha256:ollama"
    assert payload["results"]["lockstep"]["total_cost_usd"] == 0


def test_build_leaderboard_is_reproducible_and_keeps_both_modes(tmp_path):
    episodes = [
        episode("lock-1", "lockstep", 3, 45),
        episode("real-1", "realtime", 3, 55, success=True),
    ]
    entry = tmp_path / "submissions" / "example" / "submission.json"
    build_submission(episodes, METADATA, write_records(tmp_path, episodes), entry)
    output = tmp_path / "rendered"

    result = build_leaderboard(entry.parent.parent, output)

    assert result["submissions"] == 1
    assert result["rows"][0]["best"]["score"] == 55
    assert "Lockstep result" in (output / "README.md").read_text()
    assert {
        "lockstep-latency-score.svg",
        "lockstep-cost-score.svg",
        "realtime-latency-score.svg",
        "realtime-cost-score.svg",
        "mode-delta.svg",
        "best-of.svg",
        "leaderboard.json",
        "README.md",
    } <= {path.name for path in output.iterdir()}


def test_build_submission_requires_every_episode_artifact(tmp_path):
    episodes = [episode("one", "lockstep", 1, 1), episode("two", "lockstep", 2, 2)]
    paths = write_records(tmp_path, episodes)
    with pytest.raises(ValueError, match="exactly one full record"):
        build_submission(episodes, METADATA, paths[:1])


def test_pre_v1_episode_cannot_be_relabelled(tmp_path):
    old = episode("old", "lockstep", 1, 1)
    del old["config"]["benchmark_protocol"]
    with pytest.raises(ValueError, match="current benchmark protocol"):
        build_submission([old], METADATA, write_records(tmp_path, [old]))


def test_portable_legacy_reference_and_all_graphs_are_reproducible(tmp_path):
    root = Path(__file__).parents[1]
    result = build_leaderboard(
        tmp_path / "empty-submissions",
        tmp_path / "output",
        root / "leaderboard/historical/manifest.json",
    )

    assert len(result["rows"]) == 4
    assert {row["verification"] for row in result["rows"]} == {"legacy/reference (not v1)"}
    luna = next(row for row in result["rows"] if row["controller"] == "gpt-6-luna")
    assert luna["best"]["success"] is False
    assert luna["best"]["score"] == 0.0
    assert luna["lockstep"]["p95_latency_ms"] > 0
    assert luna["realtime"] is None
    for path in (tmp_path / "output").glob("*.svg"):
        ET.parse(path)
        text = path.read_text()
        assert "evidence status" in text
        assert "legacy/reference" in text or "No controller has evidence" in text
        assert all(row["controller"] in text for row in result["rows"])
        if "latency-score" in path.name or "cost-score" in path.name:
            assert "Not plotted: different/legacy cohort" in text


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", "invented-model"),
        ("type", "classical"),
        ("hardware", {"machine": "invented-GPU"}),
        ("environment", {"jsbsim": "invented"}),
        ("cost_methodology", "invented fee"),
        ("pricing_date", "2026-01-01"),
        ("verified", {"status": "verified", "method": "maintainer-reproduced"}),
    ],
)
def test_identity_provenance_and_verified_labels_cannot_be_rewritten(tmp_path, field, value):
    records = [episode("one", "lockstep", 42, 0)]
    output = tmp_path / "entry" / "submission.json"
    payload = build_submission(records, METADATA, write_records(tmp_path, records), output)
    if field in {"model", "type"}:
        payload["controller"][field] = value
    elif field == "verified":
        payload["verification"] = value
    else:
        payload["provenance"][field] = value
    with pytest.raises(ValueError):
        validate_submission(payload, output.parent)


def test_mixed_models_nonparticipant_and_continuous_ai_evidence_are_rejected(tmp_path):
    records = [episode("one", "lockstep", 42, 0), episode("two", "lockstep", 43, 0)]
    records[1]["config"]["model"] = "different"
    with pytest.raises(ValueError, match="one controller/model/type"):
        build_submission(records, METADATA, write_records(tmp_path, records))
    record = episode("one", "lockstep", 42, 0)
    record["config"]["protocol_participant"] = False
    with pytest.raises(ValueError, match="categorical protocol"):
        build_submission([record], METADATA, write_records(tmp_path, [record]))
    record["config"]["protocol_participant"] = True
    record["decisions"][0]["action"]["aileron"] = 0.7
    with pytest.raises(ValueError, match="canonical action IDs"):
        build_submission([record], METADATA, write_records(tmp_path, [record]))


def test_verified_publication_uses_trusted_submission_digest_not_claim(tmp_path):
    import hashlib

    records = [episode("one", "lockstep", 42, 0)]
    output = tmp_path / "submissions" / "entry" / "submission.json"
    build_submission(records, METADATA, write_records(tmp_path, records), output)
    registry = tmp_path / "verified.json"
    digest = "sha256:" + hashlib.sha256(output.read_bytes()).hexdigest()
    registry.write_text(
        json.dumps(
            {
                digest: {
                    "method": "maintainer-reproduced",
                    "notes": "Trusted reproduction evidence URL and run IDs.",
                }
            }
        )
    )
    ordinary = build_leaderboard(output.parent.parent, tmp_path / "community")
    trusted = build_leaderboard(
        output.parent.parent, tmp_path / "trusted", verified_registry=registry
    )
    assert ordinary["rows"][0]["verification"] == "community"
    assert trusted["rows"][0]["verification"] == "verified"
    payload = json.loads(output.read_text())
    payload["controller"]["name"] = "Changed after reproduction"
    output.write_text(json.dumps(payload))
    changed = build_leaderboard(
        output.parent.parent, tmp_path / "changed", verified_registry=registry
    )
    assert changed["rows"][0]["verification"] == "community"


@pytest.mark.parametrize("field", ["name", "slug"])
def test_captured_display_identity_cannot_be_relabelled(tmp_path, field):
    record = episode("one", "lockstep", 42, 0)
    metadata = {**METADATA, "slug": "example-1"}
    record["config"]["controller_metadata"].update(
        {"name": metadata["name"], "slug": metadata["slug"]}
    )
    output = tmp_path / "entry" / "submission.json"
    payload = build_submission([record], metadata, write_records(tmp_path, [record]), output)
    payload["controller"][field] = "unrelated-controller"
    with pytest.raises(ValueError, match="audit metadata"):
        validate_submission(payload, output.parent)


def test_uncollected_remote_request_cost_remains_unknown(tmp_path):
    record = episode("pending", "realtime", 42, 0, cost=0.01)
    record["diagnostics"].update(requests_started=3, requests_completed=3, usage_unknown_requests=1)
    metadata = METADATA | {"local": False, "cost_kind": "provider_fee"}
    payload = build_submission([record], metadata, write_records(tmp_path, [record]))
    assert payload["results"]["realtime"]["total_cost_usd"] is None


@pytest.mark.parametrize("name", ["codex", "jev"])
def test_builtin_mock_provider_real_physics_eval_roundtrip(monkeypatch, tmp_path, name):
    from flightbench import benchmark
    from flightbench.environment import FixedWingLandingEnv

    monkeypatch.setattr(
        benchmark,
        "FixedWingLandingEnv",
        lambda **kw: FixedWingLandingEnv(**(kw | {"max_time_s": 0.05})),
    )
    monkeypatch.setattr(benchmark, "make_controller", lambda *a, **kw: _builtin_controller(name)[0])
    output = tmp_path / name
    benchmark.evaluate(
        [
            "--controller",
            name,
            "--seeds",
            "42",
            "--modes",
            "lockstep,realtime",
            "--output-dir",
            str(output),
        ]
    )
    submission = validate_submission(json.loads((output / "submission.json").read_text()), output)
    assert set(submission.results) == {"lockstep", "realtime"}
    assert all(result.total_runs == 1 for result in submission.results.values())


def test_v2_score_recomputes_and_cannot_be_relabeled(tmp_path):
    from flightbench.scoring import evaluate

    record = episode("scoring-v2", "lockstep", 42, 0)
    record["config"]["scoring_version"] = "v2"
    result = evaluate(None, trajectory={"lateral": 1.0, "pitch": 2.0, "glide": 3.0})
    record["final_state"]["result"] = result
    record["outcome"].update(quality=0.0, success=False)
    path = tmp_path / "submission.json"
    payload = build_submission([record], METADATA, write_records(tmp_path, [record]), path)
    assert validate_submission(payload, path.parent).evaluation.scoring_version == "v2"
    payload["evaluation"]["scoring_version"] = "v1"
    with pytest.raises(ValueError, match="evaluation config"):
        validate_submission(payload, path.parent)
    payload["evaluation"]["scoring_version"] = "v2"
    payload["evaluation"]["scoring_config_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="scoring config hash"):
        validate_submission(payload, path.parent)
    from flightbench.leaderboard import _validate_scoring

    record["final_state"]["result"]["components"]["total_error"] = 0
    with pytest.raises(ValueError, match="trajectory integrals"):
        _validate_scoring(record)


def test_v2_validation_rejects_missing_trajectory_evidence(tmp_path):
    from flightbench.scoring import evaluate

    record = episode("scoring-v2-missing-trajectory", "lockstep", 42, 0)
    record["config"]["scoring_version"] = "v2"
    result = evaluate(None, trajectory={"lateral": 1.0, "pitch": 2.0, "glide": 3.0})
    del result["trajectory_error_integrals"]
    record["final_state"]["result"] = result
    record["outcome"].update(quality=0.0, success=False)
    path = tmp_path / "submission.json"
    payload = build_submission([record], METADATA, write_records(tmp_path, [record]), path)

    with pytest.raises(ValueError, match="finite, nonnegative, and complete"):
        validate_submission(payload, path.parent)
