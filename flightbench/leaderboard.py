"""Versioned community submissions and dependency-free leaderboard rendering."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import shutil
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from statistics import mean, median
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from .protocol import (
    ACTION_SPACE_SHA256,
    ACTION_SPACE_VERSION,
    BENCHMARK_PROTOCOL,
    command_from_action_ids,
)


class ControllerMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1, max_length=120)
    slug: str | None = Field(default=None, min_length=1, max_length=200)
    type: Literal["ai", "classical", "human", "reference"]
    provider: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=200)
    source_url: str
    license: str = Field(min_length=1, max_length=80)
    local: bool = False
    cost_kind: Literal["provider_fee", "local_provider_fee", "unknown"] = "unknown"
    parameter_count: int | None = Field(default=None, ge=1)
    quantization: str | None = Field(default=None, max_length=80)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_external_metadata(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        data = dict(value)
        if "type" not in data and "controller_type" in data:
            data["type"] = data.pop("controller_type")
        known = set(cls.model_fields)
        extra = dict(data.pop("metadata", {}))
        for key in list(data):
            if key not in known:
                extra[key] = data.pop(key)
        data["metadata"] = extra
        return data

    @model_validator(mode="after")
    def infer_cost_kind(self) -> ControllerMetadata:
        if self.type == "reference":
            self.local = True
        if self.cost_kind == "unknown" and self.local:
            self.cost_kind = "local_provider_fee"
        return self

    @field_validator("source_url")
    @classmethod
    def source_url_is_http(cls, value: str) -> str:
        if not value.startswith(("https://", "http://")) or any(
            character in value for character in " \t\r\n()[]"
        ):
            raise ValueError("source_url must be a Markdown-safe http or https URL")
        return value


class FlightBenchIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    benchmark_protocol: str
    action_space_version: str
    action_space_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Evaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    seeds: list[int] = Field(min_length=1)
    modes: list[Literal["lockstep", "realtime"]] = Field(min_length=1)
    scenario: Literal["easy", "medium"]
    decision_hz: Literal[2, 5, 10]
    time_scale_by_mode: dict[Literal["lockstep", "realtime"], float]

    @model_validator(mode="after")
    def unique_values(self) -> Evaluation:
        if len(self.seeds) != len(set(self.seeds)):
            raise ValueError("evaluation seeds must be unique")
        if any(seed < 0 or seed > 4294967295 for seed in self.seeds):
            raise ValueError("evaluation seeds must be unsigned 32-bit integers")
        if len(self.modes) != len(set(self.modes)):
            raise ValueError("evaluation modes must be unique")
        if set(self.time_scale_by_mode) != set(self.modes):
            raise ValueError("time_scale_by_mode must match evaluation modes")
        if any(value not in {1.0, 0.5, 0.25} for value in self.time_scale_by_mode.values()):
            raise ValueError("time scales must be 1.0, 0.5, or 0.25")
        if self.time_scale_by_mode.get("lockstep", 1.0) != 1.0:
            raise ValueError("lockstep time scale must be 1.0")
        return self


class ModeMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    total_runs: int = Field(ge=1)
    successful_landings: int = Field(ge=0)
    success_rate: float = Field(ge=0, le=1)
    mean_score: float = Field(ge=0, le=100)
    median_score: float = Field(ge=0, le=100)
    terminal_outcomes: dict[str, int]
    mean_latency_ms: float = Field(ge=0)
    p50_latency_ms: float = Field(ge=0)
    p95_latency_ms: float = Field(ge=0)
    max_latency_ms: float = Field(ge=0)
    effective_decisions_per_second: float = Field(ge=0)
    deadline_misses: int = Field(ge=0)
    deadline_miss_rate: float = Field(ge=0, le=1)
    stale_decisions: int = Field(ge=0)
    stale_decision_rate: float = Field(ge=0, le=1)
    total_cost_usd: float | None = Field(default=None, ge=0)
    cost_per_run_usd: float | None = Field(default=None, ge=0)
    cost_per_100_decisions_usd: float | None = Field(default=None, ge=0)
    cost_per_success_usd: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def counts_are_consistent(self) -> ModeMetrics:
        if self.successful_landings > self.total_runs:
            raise ValueError("successful_landings cannot exceed total_runs")
        if sum(self.terminal_outcomes.values()) != self.total_runs:
            raise ValueError("terminal_outcomes must sum to total_runs")
        if self.p50_latency_ms > self.p95_latency_ms or self.p95_latency_ms > self.max_latency_ms:
            raise ValueError("latency percentiles must be ordered")
        return self


class RunResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    run_id: str = Field(min_length=1, max_length=100)
    seed: int = Field(ge=0, le=4294967295)
    mode: Literal["lockstep", "realtime"]
    success: bool
    score: float = Field(ge=0, le=100)
    terminal_outcome: str = Field(min_length=1, max_length=100)
    artifact_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class Artifact(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    path: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    bytes: int = Field(ge=1, le=100 * 1024 * 1024)
    media_type: Literal["application/json", "application/gzip"]

    @field_validator("path")
    @classmethod
    def safe_relative_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("artifact path must be repository-relative and cannot contain '..'")
        return path.as_posix()


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    generated_at: datetime
    generated_by: str = "flightbench leaderboard"
    hardware: dict[str, JsonValue] = Field(default_factory=dict)
    environment: dict[str, str] = Field(default_factory=dict)
    pricing_date: date | None = None
    cost_methodology: str | None = None

    @field_validator("generated_at", mode="before")
    @classmethod
    def parse_generated_at(cls, value: object) -> object:
        return datetime.fromisoformat(value) if isinstance(value, str) else value

    @field_validator("pricing_date", mode="before")
    @classmethod
    def parse_pricing_date(cls, value: object) -> object:
        return date.fromisoformat(value) if isinstance(value, str) else value


class Verification(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["community"] = "community"
    method: Literal["self-reported"] = "self-reported"
    notes: str | None = Field(default=None, max_length=1000)


class Submission(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    controller: ControllerMetadata
    flightbench: FlightBenchIdentity
    evaluation: Evaluation
    results: dict[Literal["lockstep", "realtime"], ModeMetrics]
    runs: list[RunResult] = Field(min_length=1)
    artifacts: list[Artifact] = Field(min_length=1)
    provenance: Provenance
    verification: Verification = Field(default_factory=Verification)

    @model_validator(mode="after")
    def evaluation_matches_results(self) -> Submission:
        if set(self.evaluation.modes) != set(self.results):
            raise ValueError("evaluation modes must match result modes")
        if set(self.evaluation.seeds) != {run.seed for run in self.runs}:
            raise ValueError("evaluation seeds must match run seeds")
        if set(self.evaluation.modes) != {run.mode for run in self.runs}:
            raise ValueError("evaluation modes must match run modes")
        expected_trials = {
            (seed, mode) for seed in self.evaluation.seeds for mode in self.evaluation.modes
        }
        observed_trials = {(run.seed, run.mode) for run in self.runs}
        if observed_trials != expected_trials or len(observed_trials) != len(self.runs):
            raise ValueError("runs must contain exactly one trial for every seed and mode")
        hashes = {artifact.sha256 for artifact in self.artifacts}
        if any(run.artifact_sha256 not in hashes for run in self.runs):
            raise ValueError("every run must link to an included evidence artifact")
        for mode, metrics in self.results.items():
            runs = [run for run in self.runs if run.mode == mode]
            if metrics.total_runs != len(runs):
                raise ValueError(f"{mode} total_runs does not match run records")
            if metrics.successful_landings != sum(run.success for run in runs):
                raise ValueError(f"{mode} successful_landings does not match run records")
            if metrics.terminal_outcomes != dict(Counter(run.terminal_outcome for run in runs)):
                raise ValueError(f"{mode} terminal_outcomes do not match run records")
        return self


def _sha256(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = round((len(ordered) - 1) * percentile)
    return float(ordered[index])


def _episode_fields(episode: Mapping) -> tuple[Mapping, Mapping, Mapping]:
    return (
        episode.get("config") or episode,
        episode.get("outcome") or episode,
        episode.get("diagnostics") or episode,
    )


def _controller_identity(record: Mapping) -> tuple[str, str, str]:
    config = record["config"]
    name = config["controller"]
    metadata = config.get("controller_metadata") or {}
    kind = metadata.get("controller_type", metadata.get("type"))
    if kind is None:
        kind = (
            "ai"
            if name in {"jev", "codex", "ollama", "systemone"}
            else "reference"
            if name in {"hold", "random", "baseline"}
            else "human"
            if name == "human"
            else None
        )
    if kind is None:
        raise ValueError("evidence must declare its controller type")
    return name, config.get("model") or name, kind


def _bind_controller(controller: ControllerMetadata, episodes: Sequence[Mapping]) -> None:
    identities = {_controller_identity(record) for record in episodes}
    if len(identities) != 1:
        raise ValueError("evidence must share one controller/model/type identity")
    _, model, kind = identities.pop()
    if (controller.model, controller.type) != (model, kind):
        raise ValueError("submission controller/model/type does not match evidence")
    for record in episodes:
        config = record["config"]
        runtime = config.get("controller_metadata") or {}
        for key, value in runtime.items():
            if key in {"type", "controller_type"}:
                continue
            reported = (
                getattr(controller, key)
                if key in ControllerMetadata.model_fields
                else controller.metadata.get(key)
            )
            if reported != value:
                raise ValueError(f"controller audit metadata does not match evidence: {key}")
        if kind != "ai":
            continue
        if config.get("protocol_participant") is not True:
            raise ValueError("AI evidence must participate in the categorical protocol")
        for decision in record.get("decisions", []):
            if decision.get("error"):
                continue
            info = decision.get("decision_info") or {}
            command = command_from_action_ids(info.get("action_ids", {})).model_dump()
            if info.get("command") != command:
                raise ValueError("AI decision command does not match canonical action IDs")
            if decision.get("applied", True) and decision.get("action") != command:
                raise ValueError("AI applied command does not match canonical action IDs")


def _mode_metrics(
    episodes: Sequence[Mapping], default_episode_cost: float | None = None
) -> ModeMetrics:
    outcomes = [_episode_fields(episode)[1] for episode in episodes]
    diagnostics = [_episode_fields(episode)[2] for episode in episodes]
    latencies = [
        float(decision.get("latency_ms", 0))
        for episode in episodes
        for decision in episode.get("decisions", [])
        if decision.get("latency_ms") is not None
    ]
    scores = [float(outcome.get("quality", outcome.get("score", 0))) for outcome in outcomes]
    successes = sum(bool(outcome.get("success")) for outcome in outcomes)
    applied_decisions = sum(int(row.get("decision_count", 0)) for row in diagnostics)
    calls = sum(int(row.get("calls", row.get("decision_count", 0))) for row in diagnostics)
    duration = sum(float(row.get("duration_s", 0)) for row in diagnostics)
    late = sum(int(row.get("late_decisions", 0)) for row in diagnostics)
    stale = sum(int(row.get("stale_decisions", 0)) for row in diagnostics)
    costs = []
    for episode in episodes:
        diagnostics_cost = _episode_fields(episode)[2].get("cost_usd")
        value = episode.get("cost_usd") if episode.get("cost_usd") is not None else diagnostics_cost
        if value is None:
            value = default_episode_cost
        if value is not None:
            costs.append(value)
    total_cost = sum(float(value) for value in costs) if len(costs) == len(episodes) else None
    if not latencies:
        latencies = [float(row.get("mean_latency_ms", 0)) for row in diagnostics]
    return ModeMetrics(
        total_runs=len(episodes),
        successful_landings=successes,
        success_rate=successes / len(episodes),
        mean_score=mean(scores),
        median_score=median(scores),
        terminal_outcomes=dict(Counter(str(row.get("status", "unknown")) for row in outcomes)),
        mean_latency_ms=mean(latencies),
        p50_latency_ms=_percentile(latencies, 0.50),
        p95_latency_ms=_percentile(latencies, 0.95),
        max_latency_ms=max(latencies),
        effective_decisions_per_second=applied_decisions / duration if duration else 0,
        deadline_misses=late,
        deadline_miss_rate=late / calls if calls else 0,
        stale_decisions=stale,
        stale_decision_rate=stale / calls if calls else 0,
        total_cost_usd=total_cost,
        cost_per_run_usd=total_cost / len(episodes) if total_cost is not None else None,
        cost_per_100_decisions_usd=(total_cost * 100 / calls)
        if total_cost is not None and calls
        else None,
        cost_per_success_usd=(total_cost / successes)
        if total_cost is not None and successes
        else None,
    )


def _read_artifact(path: Path) -> dict:
    limit = 100 * 1024 * 1024
    if path.suffix == ".gz":
        with gzip.open(path, "rb") as source:
            data = source.read(limit + 1)
    else:
        data = path.read_bytes()
    if len(data) > limit:
        raise ValueError(f"artifact expands beyond 100 MiB: {path}")
    return json.loads(data)


def _portable_artifacts(paths: Sequence[Path], output_path: Path | None) -> list[tuple[Path, str]]:
    artifacts = []
    for source in paths:
        source = Path(source)
        if output_path is None:
            artifacts.append((source, source.name))
            continue
        if source.suffix == ".gz" and source.resolve().is_relative_to(output_path.parent.resolve()):
            artifacts.append(
                (source, source.resolve().relative_to(output_path.parent.resolve()).as_posix())
            )
            continue
        evidence_dir = output_path.parent / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        name = source.name if source.suffix == ".gz" else source.name + ".gz"
        target = evidence_dir / name
        if source.resolve() != target.resolve():
            if target.exists():
                raise FileExistsError(target)
            if source.suffix == ".gz":
                shutil.copyfile(source, target)
            else:
                target.write_bytes(gzip.compress(source.read_bytes(), mtime=0))
        artifacts.append((target, target.relative_to(output_path.parent).as_posix()))
    return artifacts


def build_submission(
    episodes: Sequence[Mapping],
    controller_metadata: Mapping,
    artifact_paths: Sequence[Path],
    output_path: Path | None = None,
) -> dict:
    """Build and optionally write one strict, portable v1 submission."""
    if not episodes or not artifact_paths:
        raise ValueError("episodes and their evidence artifacts are required")
    if output_path is not None and Path(output_path).exists():
        raise FileExistsError(output_path)
    # Compare and aggregate the same JSON representation written as evidence (tuples become lists).
    episodes = [json.loads(json.dumps(dict(episode), allow_nan=False)) for episode in episodes]
    configs = [_episode_fields(episode)[0] for episode in episodes]
    scenarios = {row.get("scenario") for row in configs}
    rates = {row.get("decision_hz") for row in configs}
    source_hashes = {
        (episode.get("source_identity") or {}).get("source_hash") for episode in episodes
    }
    commits = {(episode.get("source_identity") or {}).get("git_commit") for episode in episodes}
    if any(
        len(values) != 1 or None in values for values in (scenarios, rates, source_hashes, commits)
    ):
        raise ValueError("episodes must share scenario, decision rate, source hash, and git commit")
    for config in configs:
        if (
            config.get("benchmark_protocol") != BENCHMARK_PROTOCOL
            or config.get("action_space_version") != ACTION_SPACE_VERSION
            or config.get("action_space_sha256") != ACTION_SPACE_SHA256
        ):
            raise ValueError("episodes are not records of the current benchmark protocol")
    scales_by_mode = {
        mode: {float(row.get("time_scale", 1.0)) for row in configs if row.get("mode") == mode}
        for mode in ("lockstep", "realtime")
    }
    if any(len(scales_by_mode[mode]) != 1 for mode in scales_by_mode if scales_by_mode[mode]):
        raise ValueError("episodes in one mode must share a time scale")

    metadata_input = dict(controller_metadata)
    verification_input = metadata_input.pop("verification", None)
    controller = ControllerMetadata.model_validate(metadata_input)
    _bind_controller(controller, episodes)
    portable = _portable_artifacts(artifact_paths, Path(output_path) if output_path else None)
    artifact_models = []
    artifact_run_ids = {}
    artifact_records = {}
    for path, relative in portable:
        data = path.read_bytes()
        digest = _sha256(data)
        record = _read_artifact(path)
        run_id = record.get("run_id")
        if run_id:
            artifact_run_ids[str(run_id)] = digest
            artifact_records[str(run_id)] = record
        artifact_models.append(
            Artifact(
                path=relative,
                sha256=digest,
                bytes=len(data),
                media_type="application/gzip" if path.suffix == ".gz" else "application/json",
            )
        )
    expected_ids = {str(episode.get("run_id")) for episode in episodes}
    if (
        len(portable) != len(episodes)
        or len(artifact_run_ids) != len(episodes)
        or len({relative for _, relative in portable}) != len(episodes)
        or None in {episode.get("run_id") for episode in episodes}
        or expected_ids != set(artifact_run_ids)
    ):
        raise ValueError("artifact_paths must contain exactly one full record for every episode")
    if any(artifact_records[str(episode["run_id"])] != episode for episode in episodes):
        raise ValueError("evidence artifact content must exactly match its episode record")

    by_mode = {
        mode: [episode for episode in episodes if _episode_fields(episode)[0].get("mode") == mode]
        for mode in ("lockstep", "realtime")
    }
    by_mode = {mode: rows for mode, rows in by_mode.items() if rows}
    runs = []
    for episode in episodes:
        config, outcome, _ = _episode_fields(episode)
        run_id = str(episode["run_id"])
        runs.append(
            RunResult(
                run_id=run_id,
                seed=int(config["seed"]),
                mode=config["mode"],
                success=bool(outcome.get("success")),
                score=float(outcome.get("quality", outcome.get("score", 0))),
                terminal_outcome=str(outcome.get("status", "unknown")),
                artifact_sha256=artifact_run_ids[run_id],
            )
        )
    submission = Submission(
        schema_version=1,
        controller=controller,
        flightbench=FlightBenchIdentity(
            commit=commits.pop(),
            source_hash=source_hashes.pop(),
            benchmark_protocol=BENCHMARK_PROTOCOL,
            action_space_version=ACTION_SPACE_VERSION,
            action_space_sha256=ACTION_SPACE_SHA256,
        ),
        evaluation=Evaluation(
            seeds=sorted({int(row["seed"]) for row in configs}),
            modes=list(by_mode),
            scenario=scenarios.pop(),
            decision_hz=rates.pop(),
            time_scale_by_mode={mode: scales_by_mode[mode].pop() for mode in by_mode},
        ),
        results={
            mode: _mode_metrics(rows, 0.0 if controller.cost_kind == "local_provider_fee" else None)
            for mode, rows in by_mode.items()
        },
        runs=runs,
        artifacts=artifact_models,
        provenance=Provenance(
            generated_at=datetime.now(UTC),
            hardware=(episodes[0].get("source_identity") or {}).get("hardware") or {},
            environment=(episodes[0].get("source_identity") or {}).get("versions") or {},
            pricing_date=controller.metadata.get("pricing_date"),
            cost_methodology=controller.metadata.get("cost_methodology"),
        ),
        verification=Verification.model_validate(verification_input)
        if verification_input
        else Verification(),
    )
    payload = submission.model_dump(mode="json")
    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("x", encoding="utf-8") as output:
            output.write(json.dumps(payload, indent=2) + "\n")
    return payload


def validate_submission(data: Mapping, base_dir: Path | None = None) -> Submission:
    submission = Submission.model_validate(data)
    if (
        submission.flightbench.benchmark_protocol != BENCHMARK_PROTOCOL
        or submission.flightbench.action_space_version != ACTION_SPACE_VERSION
        or submission.flightbench.action_space_sha256 != ACTION_SPACE_SHA256
    ):
        raise ValueError("submission does not use the current benchmark protocol")
    if base_dir is not None:
        records = {}
        for artifact in submission.artifacts:
            path = Path(base_dir) / artifact.path
            if not path.is_file():
                raise ValueError(f"missing artifact: {artifact.path}")
            payload = path.read_bytes()
            if len(payload) != artifact.bytes or _sha256(payload) != artifact.sha256:
                raise ValueError(f"artifact hash or size mismatch: {artifact.path}")
            record = _read_artifact(path)
            if record.get("run_id"):
                records[artifact.sha256] = record
        evidence_episodes = []
        for run in submission.runs:
            record = records.get(run.artifact_sha256)
            if record is None:
                raise ValueError(f"run evidence is not a full episode record: {run.run_id}")
            config, outcome, _ = _episode_fields(record)
            observed = (
                str(record.get("run_id")),
                int(config.get("seed", -1)),
                config.get("mode"),
                bool(outcome.get("success")),
                float(outcome.get("quality", outcome.get("score", 0))),
                str(outcome.get("status", "unknown")),
            )
            expected = (
                run.run_id,
                run.seed,
                run.mode,
                run.success,
                run.score,
                run.terminal_outcome,
            )
            if observed != expected:
                raise ValueError(f"run summary does not match evidence: {run.run_id}")
            if (
                config.get("benchmark_protocol") != submission.flightbench.benchmark_protocol
                or config.get("action_space_version") != submission.flightbench.action_space_version
                or config.get("action_space_sha256") != submission.flightbench.action_space_sha256
                or (record.get("source_identity") or {}).get("source_hash")
                != submission.flightbench.source_hash
                or (record.get("source_identity") or {}).get("git_commit")
                != submission.flightbench.commit
            ):
                raise ValueError(f"run provenance does not match submission: {run.run_id}")
            evidence_episodes.append(record)
        _bind_controller(submission.controller, evidence_episodes)
        if submission.provenance.cost_methodology != submission.controller.metadata.get(
            "cost_methodology"
        ) or submission.provenance.pricing_date != (
            date.fromisoformat(submission.controller.metadata["pricing_date"])
            if submission.controller.metadata.get("pricing_date")
            else None
        ):
            raise ValueError("cost provenance does not match controller evidence metadata")
        for record in evidence_episodes:
            identity = record.get("source_identity") or {}
            if (
                identity.get("hardware", {}) != submission.provenance.hardware
                or identity.get("versions", {}) != submission.provenance.environment
            ):
                raise ValueError("hardware/environment provenance does not match evidence")
        for mode, metrics in submission.results.items():
            expected_metrics = _mode_metrics(
                [
                    episode
                    for episode in evidence_episodes
                    if _episode_fields(episode)[0]["mode"] == mode
                ],
                0.0 if submission.controller.cost_kind == "local_provider_fee" else None,
            )
            if metrics != expected_metrics:
                raise ValueError(f"{mode} metrics do not match evidence")
    return submission


def load_submissions(root: Path) -> list[tuple[Path, Submission]]:
    rows = []
    for path in sorted(Path(root).glob("*/submission.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        rows.append((path, validate_submission(data, path.parent)))
    return rows


def _display_rows(submissions: Sequence[tuple[Path, Submission]], verified: Mapping) -> list[dict]:
    rows = []
    for path, submission in submissions:
        row = {
            "controller": submission.controller.name,
            "model": submission.controller.model,
            "source": submission.controller.source_url,
            "verification": "verified" if _sha256(path.read_bytes()) in verified else "community",
            "submission": "/".join(path.parts[path.parts.index("submissions") :])
            if "submissions" in path.parts
            else path.name,
        }
        for mode in ("lockstep", "realtime"):
            metrics = submission.results.get(mode)
            row[mode] = metrics.model_dump(mode="json") if metrics else None
        completed = [
            run
            for run in submission.runs
            if run.terminal_outcome
            not in {"error", "interrupted", "controller_error", "controller_timeout"}
        ]
        landed = [run for run in completed if run.success]
        best = max(landed or completed, key=lambda run: run.score, default=None)
        row["best"] = best.model_dump(mode="json") if best else None
        rows.append(row)
    return rows


def _historical_rows(path: Path | None) -> list[dict]:
    """Load the curated pre-v1 manifest as references, never as v1 submissions."""
    if path is None or not Path(path).is_file():
        return []
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    recorded_latencies = {}
    if manifest.get("schema_version") == "legacy-reference-1":
        for run in manifest.get("runs", []):
            artifact = Path(path).parent / run["artifact_path"]
            compressed = artifact.read_bytes()
            if _sha256(compressed).removeprefix("sha256:") != run["artifact_sha256"]:
                raise ValueError(f"legacy artifact hash mismatch: {artifact}")
            raw = gzip.decompress(compressed)
            if hashlib.sha256(raw).hexdigest() != run["record_sha256"]:
                raise ValueError(f"legacy record hash mismatch: {artifact}")
            record = json.loads(raw)
            recorded_latencies[run["run_id"]] = [
                float(decision["latency_ms"])
                for decision in record.get("decisions", [])
                if decision.get("latency_ms") is not None
            ]
            outcome = record.get("outcome") or record
            config = record.get("config") or record
            observed = (
                record.get("run_id"),
                config.get("seed"),
                config.get("mode"),
                outcome.get("success"),
                float(outcome.get("quality", outcome.get("score", 0))),
                outcome.get("status"),
            )
            expected = (
                run["run_id"],
                run["seed"],
                run["mode"],
                run["success"],
                float(run["score"]),
                run["status"],
            )
            if observed != expected:
                raise ValueError(f"legacy record summary mismatch: {artifact}")
    groups: dict[tuple[str, str], list[dict]] = {}
    for run in manifest.get("runs", []):
        groups.setdefault((run["controller"], run["model"]), []).append(run)
    rows = []
    for (controller, model), runs in groups.items():
        row = {
            "controller": "Jev" if controller == "jev" else model.removeprefix("openai-codex/"),
            "model": model,
            "source": "https://github.com/AlperKartkaya/FlightBench",
            "verification": "legacy/reference (not v1)",
            "submission": "historical/manifest.json"
            if manifest.get("schema_version") == "legacy-reference-1"
            else "../" + Path(path).as_posix(),
        }
        for mode in ("lockstep", "realtime"):
            selected = [run for run in runs if run["mode"] == mode]
            costs = [run.get("estimated_api_cost_usd") for run in selected]
            latencies = [
                latency for run in selected for latency in recorded_latencies.get(run["run_id"], [])
            ]
            row[mode] = (
                {
                    "total_runs": len(selected),
                    "successful_landings": sum(run["success"] for run in selected),
                    "success_rate": sum(run["success"] for run in selected) / len(selected),
                    "median_score": median(run["score"] for run in selected),
                    "p50_latency_ms": _percentile(latencies, 0.50) if latencies else None,
                    "p95_latency_ms": _percentile(latencies, 0.95) if latencies else None,
                    "cost_per_run_usd": mean(costs) if all(x is not None for x in costs) else None,
                }
                if selected
                else None
            )
        landed = [run for run in runs if run["success"]]
        best = max(landed or runs, key=lambda run: run["score"])
        row["best"] = {
            "run_id": best["run_id"],
            "seed": best["seed"],
            "mode": best["mode"],
            "success": best["success"],
            "score": best["score"],
            "terminal_outcome": best["status"],
        }
        rows.append(row)
    return rows


def _markdown(rows: Sequence[dict]) -> str:
    lines = [
        "# FlightBench community leaderboard",
        "",
        "Realtime and lockstep are evaluation modes over the same architecture-neutral controller roster. Community results are self-reported until independently reproduced.",
        "",
        "| Controller | Status | Lockstep success / score | Realtime success / score | p50 / p95 realtime latency | Evidence |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        controller_name = html.escape(row["controller"]).replace("|", "\\|")
        values = []
        for mode in ("lockstep", "realtime"):
            metrics = row[mode]
            values.append(
                f"{metrics['successful_landings']}/{metrics['total_runs']} ({metrics['success_rate']:.0%}) / {metrics['median_score']:.2f}"
                if metrics
                else "—"
            )
        rt = row["realtime"]
        latency = (
            f"{rt['p50_latency_ms']:.1f} / {rt['p95_latency_ms']:.1f} ms"
            if rt and rt.get("p50_latency_ms") is not None and rt.get("p95_latency_ms") is not None
            else "—"
        )
        lines.append(
            f"| [{controller_name}]({row['source']}) | {row['verification']} | {values[0]} | {values[1]} | {latency} | [submission]({row['submission']}) |"
        )
    lines.extend(
        [
            "",
            "## Graphs",
            "",
            "| Mode | Latency vs score | Provider cost vs score |",
            "| --- | --- | --- |",
            "| Lockstep | [Graph](lockstep-latency-score.svg) | [Graph](lockstep-cost-score.svg) |",
            "| Realtime | [Graph](realtime-latency-score.svg) | [Graph](realtime-cost-score.svg) |",
            "",
            "[Mode delta](mode-delta.svg) · [Best completed trial per controller](best-of.svg)",
            "",
            "![Best completed trial, successful landing preferred](best-of.svg)",
            "",
            "A failed trial is not a successful landing. Legacy Jev/Codex references retain their original protocols and rates; absent mode evidence is never invented. Historical Codex costs are API-price equivalents, not subscription charges; Jev uses a logged-character token estimate.",
            "Historical references are curated records, not a new evaluation cohort. In particular, Jev contributes one selected successful run: 1/1 here is not its overall historical success rate.",
            "",
            "## Submit a result",
            "",
            "1. Evaluate the same controller in lockstep and realtime with declared seeds.",
            "2. Generate `submission.json` plus the gzip evidence records with `build_submission`.",
            "3. Add them under `leaderboard/submissions/<controller>/` and open a leaderboard PR.",
            "4. Run `python -m flightbench.leaderboard validate leaderboard/submissions/<controller>/submission.json`.",
            "",
            "CI checks schema, metrics, evidence size, and SHA-256 integrity only. It never runs submitted controllers or uses provider secrets. New entries remain **community / self-reported** until maintainers reproduce them in a trusted environment.",
            "",
            "Unknown provider cost stays unknown. A zero local provider fee excludes hardware and energy unless provenance explicitly says otherwise.",
        ]
    )
    return "\n".join(lines) + "\n"


_COLORS = (
    "#2563eb",
    "#dc2626",
    "#059669",
    "#9333ea",
    "#ea580c",
    "#0891b2",
    "#4f46e5",
    "#65a30d",
    "#a16207",
)


def _short(value: str, length: int = 30) -> str:
    return value if len(value) <= length else value[: length - 1] + "…"


def _status(row: Mapping) -> str:
    return "legacy/reference" if "legacy" in row["verification"] else row["verification"]


def _svg_scatter(rows: Sequence[dict], mode: str, x_key: str, title: str, x_label: str) -> str:
    points = [
        (index, row, float(row[mode][x_key]), float(row[mode]["median_score"]))
        for index, row in enumerate(rows)
        if row.get(mode) and row[mode].get(x_key) is not None
    ]
    width, height, left, right, top, bottom = (
        1040,
        max(460, 150 + len(rows) * 42),
        75,
        680,
        55,
        70,
    )
    max_x = max((point[2] for point in points), default=1000 if "latency" in x_key else 1) or 1
    coincident = Counter((point[2], point[3]) for point in points)
    rings = Counter()
    plot_height = height - top - bottom
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">',
        "<style>text{font:13px system-ui,sans-serif;fill:#0f172a}.grid{stroke:#cbd5e1;stroke-width:1}.axis{stroke:#334155;stroke-width:1.5}</style>",
        f'<text x="{right / 2}" y="24" text-anchor="middle" font-weight="700">{html.escape(title)}</text>',
    ]
    for tick in range(5):
        value = max_x * tick / 4
        x = left + (right - left) * tick / 4
        label = f"${value:.3g}" if "cost" in x_key else f"{value:.0f}"
        elements.extend(
            [
                f'<path class="grid" d="M{x:.1f} {top}V{height - bottom}"/>',
                f'<text x="{x:.1f}" y="{height - bottom + 22}" text-anchor="middle">{label}</text>',
            ]
        )
    for value in range(0, 101, 25):
        y = top + (100 - value) / 100 * plot_height
        elements.extend(
            [
                f'<path class="grid" d="M{left} {y:.1f}H{right}"/>',
                f'<text x="{left - 10}" y="{y + 4:.1f}" text-anchor="end">{value}</text>',
            ]
        )
    elements.extend(
        [
            f'<path class="axis" d="M{left} {top}V{height - bottom}H{right}" fill="none"/>',
            f'<text x="{(left + right) / 2}" y="{height - 18}" text-anchor="middle">{html.escape(x_label)}</text>',
            f'<text transform="translate(20 {(top + height - bottom) / 2}) rotate(-90)" text-anchor="middle">Median landing score (0–100)</text>',
            f'<text x="{right + 28}" y="52" font-weight="700">Controller · evidence status</text>',
            f'<text x="{right + 28}" y="{height - 40}" fill="#475569">Square = legacy/reference · circle = v1</text>',
            f'<text x="{right + 28}" y="{height - 24}" fill="#475569">Missing evidence is not plotted or inferred.</text>',
            f'<text x="{right + 28}" y="{height - 8}" fill="#475569">Coincident points use concentric outlines.</text>',
        ]
    )
    if not points:
        elements.append(
            f'<text x="{(left + right) / 2}" y="{top + plot_height / 2}" text-anchor="middle">No recorded {html.escape(x_label.lower())} evidence for this mode.</text>'
        )
    for row_index, row, x_value, score in points:
        color = _COLORS[row_index % len(_COLORS)]
        x = left + 6 + x_value / max_x * (right - left - 12)
        y = top + 6 + (100 - score) / 100 * (plot_height - 12)
        legacy = "legacy" in row["verification"]
        marker = (
            f'<rect x="{x - 6:.1f}" y="{y - 6:.1f}" width="12" height="12" fill="{color}"/>'
            if legacy
            else f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{color}"/>'
        )
        if coincident[x_value, score] > 1:
            radius = 4 + rings[x_value, score] * 2
            rings[x_value, score] += 1
            marker = (
                f'<rect x="{x - radius:.1f}" y="{y - radius:.1f}" width="{radius * 2}" height="{radius * 2}" fill="none" stroke="{color}" stroke-width="2"/>'
                if legacy
                else f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius}" fill="none" stroke="{color}" stroke-width="2"/>'
            )
        elements.append(
            marker
            + f"<title>{html.escape(row['controller'])}: {x_value:.4g}, score {score:.2f}</title>"
        )
    for row_index, row in enumerate(rows):
        color = _COLORS[row_index % len(_COLORS)]
        legacy = "legacy" in row["verification"]
        legend_y = 78 + row_index * 42
        legend_marker = (
            f'<rect x="{right + 28}" y="{legend_y - 9}" width="11" height="11" fill="{color}"/>'
            if legacy
            else f'<circle cx="{right + 34}" cy="{legend_y - 3}" r="6" fill="{color}"/>'
        )
        full = f"{row['controller']} · {_status(row)}"
        metrics = row.get(mode)
        value = metrics.get(x_key) if metrics else None
        detail = (
            f"{value:.4g} {'USD' if 'cost' in x_key else 'ms'} · score {metrics['median_score']:.2f}"
            if value is not None
            else "No recorded evidence for this axis/mode"
        )
        elements.extend(
            [
                legend_marker,
                f'<text x="{right + 48}" y="{legend_y}"><title>{html.escape(full)}</title>{html.escape(_short(full, 38))}</text>',
                f'<text x="{right + 48}" y="{legend_y + 16}" style="font-size:11px">{html.escape(detail)}</text>',
            ]
        )
    elements.append("</svg>\n")
    return "".join(elements)


def _svg_delta(rows: Sequence[dict]) -> str:
    paired = [row for row in rows if row["lockstep"] and row["realtime"]]
    width, height, left, right, top, bottom = (
        1040,
        max(420, 150 + len(rows) * 42),
        205,
        700,
        75,
        65,
    )
    plot_height = height - top - bottom
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="Realtime versus lockstep median score">',
        "<style>text{font:13px system-ui,sans-serif;fill:#0f172a}.grid{stroke:#cbd5e1}.axis{stroke:#334155;stroke-width:1.5}</style>",
        f'<text x="{right / 2}" y="24" text-anchor="middle" font-weight="700">Realtime versus lockstep median score</text>',
        '<circle cx="230" cy="49" r="5" fill="#334155"/><text x="242" y="53">lockstep</text><rect x="325" y="44" width="10" height="10" fill="#334155"/><text x="341" y="53">realtime</text>',
    ]
    for score in range(0, 101, 25):
        x = left + score / 100 * (right - left)
        elements.extend(
            [
                f'<path class="grid" d="M{x:.1f} {top}V{height - bottom}"/>',
                f'<text x="{x:.1f}" y="{height - bottom + 22}" text-anchor="middle">{score}</text>',
            ]
        )
    elements.extend(
        [
            f'<path class="axis" d="M{left} {height - bottom}H{right}"/>',
            f'<text x="{(left + right) / 2}" y="{height - 18}" text-anchor="middle">Median landing score (0–100)</text>',
            f'<text x="{right + 28}" y="52" font-weight="700">Controller · evidence status</text>',
            f'<text x="{right + 28}" y="{height - 36}" fill="#475569">Legend labels include v1 or legacy/reference.</text>',
            f'<text x="{right + 28}" y="{height - 20}" fill="#475569">Missing mode pairs are omitted, never inferred.</text>',
        ]
    )
    if not paired:
        elements.append(
            f'<text x="{(left + right) / 2}" y="{top + plot_height / 2}" text-anchor="middle">No controller has evidence in both modes.</text>'
        )
    for index, row in enumerate(rows):
        color = _COLORS[index % len(_COLORS)]
        y = top + 24 + index * 42
        full = f"{row['controller']} · {_status(row)}"
        elements.append(
            f'<rect x="{right + 28}" y="{y - 8}" width="12" height="12" fill="{color}"/><text x="{right + 48}" y="{y + 3}"><title>{html.escape(full)}</title>{html.escape(_short(full, 38))}</text>'
        )
        if row not in paired:
            elements.append(
                f'<text x="{right + 48}" y="{y + 18}" style="font-size:11px">No paired mode evidence</text>'
            )
            continue
        x1 = left + row["lockstep"]["median_score"] / 100 * (right - left)
        x2 = left + row["realtime"]["median_score"] / 100 * (right - left)
        full = f"{row['controller']} · {_status(row)}"
        elements.extend(
            [
                f'<text x="{left - 12}" y="{y + 4}" text-anchor="end"><title>{html.escape(full)}</title>{html.escape(_short(row["controller"], 24))}</text>',
                f'<path d="M{x1:.1f} {y}H{x2:.1f}" stroke="{color}" stroke-width="3"/>',
                f'<circle cx="{x1:.1f}" cy="{y}" r="6" fill="{color}"/><rect x="{x2 - 6:.1f}" y="{y - 6}" width="12" height="12" fill="{color}"/>',
            ]
        )
    elements.append("</svg>\n")
    return "".join(elements)


def _svg_best(rows: Sequence[dict]) -> str:
    ranked = sorted(
        (row for row in rows if row["best"]), key=lambda row: row["best"]["score"], reverse=True
    )
    width, height, left, right, top, bottom = (
        1080,
        max(440, 140 + len(ranked) * 38),
        210,
        710,
        60,
        65,
    )
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="Best completed trial per controller, successful landing preferred">',
        "<style>text{font:13px system-ui,sans-serif;fill:#0f172a}.grid{stroke:#cbd5e1}.axis{stroke:#334155;stroke-width:1.5}</style>",
        f'<text x="{right / 2}" y="24" text-anchor="middle" font-weight="700">Best completed trial per controller (successful landing preferred)</text>',
    ]
    for score in range(0, 101, 25):
        x = left + score / 100 * (right - left)
        elements.extend(
            [
                f'<path class="grid" d="M{x:.1f} {top}V{height - bottom}"/>',
                f'<text x="{x:.1f}" y="{height - bottom + 22}" text-anchor="middle">{score}</text>',
            ]
        )
    elements.extend(
        [
            f'<path class="axis" d="M{left} {height - bottom}H{right}"/>',
            f'<text x="{(left + right) / 2}" y="{height - 18}" text-anchor="middle">Best completed trial score (0–100)</text>',
            f'<text x="{right + 30}" y="52" font-weight="700">Controller · evidence status</text>',
        ]
    )
    for index, row in enumerate(ranked):
        color = _COLORS[rows.index(row) % len(_COLORS)]
        score, mode = row["best"]["score"], row["best"]["mode"]
        outcome = row["best"]["terminal_outcome"]
        y = top + 22 + index * 38
        full = f"{row['controller']} · {_status(row)}"
        elements.extend(
            [
                f'<text x="{left - 12}" y="{y + 15}" text-anchor="end"><title>{html.escape(full)}</title>{html.escape(_short(row["controller"], 25))}</text>',
                f'<rect x="{left}" y="{y}" width="{score / 100 * (right - left):.1f}" height="22" fill="{color}"><title>{html.escape(full)}: {score:.2f} ({mode}, {html.escape(outcome)})</title></rect>',
                f'<text x="{left + score / 100 * (right - left) + 8:.1f}" y="{y + 15}">{score:.2f} · {mode} · {html.escape(outcome)}</text>',
                f'<rect x="{right + 30}" y="{y + 5}" width="12" height="12" fill="{color}"/><text x="{right + 50}" y="{y + 16}"><title>{html.escape(full)}</title>{html.escape(_short(full, 40))}</text>',
            ]
        )
    elements.append("</svg>\n")
    return "".join(elements)


def _verified_registry(path: Path | None) -> dict:
    """Publication authority belongs to this maintainer-owned ledger, never submission JSON."""
    if path is None or not path.is_file():
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise TypeError("verification registry must map submission SHA-256 to reproduction proof")
    for digest, proof in data.items():
        if not isinstance(digest, str) or not digest.startswith("sha256:") or len(digest) != 71:
            raise ValueError("invalid verification registry SHA-256")
        int(digest[7:], 16)
        if (
            not isinstance(proof, dict)
            or set(proof) != {"method", "notes"}
            or proof["method"] not in {"maintainer-reproduced", "trusted-workflow"}
            or not isinstance(proof["notes"], str)
            or not 1 <= len(proof["notes"]) <= 1000
        ):
            raise ValueError(
                "verification registry entry requires reproduction method and evidence notes"
            )
    return data


def build_leaderboard(
    submissions_dir: Path,
    output_dir: Path,
    historical_path: Path | None = None,
    verified_registry: Path | None = None,
) -> dict:
    submissions = load_submissions(Path(submissions_dir))
    rows = _display_rows(submissions, _verified_registry(verified_registry)) + _historical_rows(
        historical_path
    )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "leaderboard.json").write_text(json.dumps(rows, indent=2) + "\n")
    (output_dir / "README.md").write_text(_markdown(rows), encoding="utf-8")
    for mode in ("lockstep", "realtime"):
        (output_dir / f"{mode}-latency-score.svg").write_text(
            _svg_scatter(
                rows,
                mode,
                "p95_latency_ms",
                f"{mode.title()}: p95 latency versus score",
                "p95 decision latency (ms)",
            )
        )
        (output_dir / f"{mode}-cost-score.svg").write_text(
            _svg_scatter(
                rows,
                mode,
                "cost_per_run_usd",
                f"{mode.title()}: provider cost versus score",
                "Estimated provider cost per run (USD)",
            )
        )
    (output_dir / "mode-delta.svg").write_text(_svg_delta(rows))
    (output_dir / "best-of.svg").write_text(_svg_best(rows))
    return {"submissions": len(submissions), "rows": rows}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate or build the FlightBench leaderboard")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("paths", nargs="+", type=Path)
    build = commands.add_parser("build")
    build.add_argument("--submissions-dir", type=Path, default=Path("leaderboard/submissions"))
    build.add_argument("--output-dir", type=Path, default=Path("leaderboard"))
    build.add_argument(
        "--historical",
        type=Path,
        default=Path("leaderboard/historical/manifest.json"),
        help="Optional pre-v1 reference manifest; entries stay labeled legacy/reference",
    )
    build.add_argument(
        "--verified-registry",
        type=Path,
        default=Path("leaderboard/verified.json"),
        help="Trusted maintainer-owned submission digest registry (never submission metadata)",
    )
    args = parser.parse_args(argv)
    if args.command == "validate":
        for path in args.paths:
            validate_submission(json.loads(path.read_text()), path.parent)
        return 0
    build_leaderboard(
        args.submissions_dir, args.output_dir, args.historical, args.verified_registry
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
