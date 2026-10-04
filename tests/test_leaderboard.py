import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

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
            "cost_usd": cost,
        },
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
            for latency in (10.0, 20.0)
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
    assert validated.results["realtime"].p95_latency_ms == 20
    assert validated.results["realtime"].deadline_miss_rate == 0.5
    assert validated.results["realtime"].total_cost_usd == 0
    assert {artifact.path for artifact in validated.artifacts} == {
        "evidence/lock-1.json.gz",
        "evidence/real-1.json.gz",
    }
    assert all((output.parent / artifact.path).is_file() for artifact in validated.artifacts)


def test_build_submission_compares_json_normalized_episode_to_evidence(tmp_path):
    record = episode("tuple-run", "lockstep", 42, 49)
    record["final_state"] = {"position": (1.0, 2.0, 3.0)}
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
    assert "Lockstep success" in (output / "README.md").read_text()
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
            assert "No recorded evidence for this axis/mode" in text


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
