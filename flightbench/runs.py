"""Small, local JSON run store shared by the CLI and browser server."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parent.parent
SOURCE_FILES = (
    ROOT / "pyproject.toml",
    ROOT / "uv.lock",
    ROOT / "frontend/package-lock.json",
    *sorted((ROOT / "flightbench").glob("*.py")),
    *sorted((ROOT / "frontend/src").glob("*.ts")),
)


class HumanAssistance(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    auto_center: bool = False
    wing_leveler: bool = False


class RunSettings(BaseModel):
    """One validated request contract for browser and headless runs."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)
    controller: str = Field(default="baseline", min_length=1, max_length=80)
    model: str | None = Field(default=None, max_length=200)
    scenario: Literal["easy", "medium"] = "easy"
    mode: Literal["lockstep", "realtime"] = "lockstep"
    seed: int = Field(default=42, ge=0, le=4294967295)
    decision_hz: Literal[2, 5, 10] = 2
    time_scale: Literal[1.0, 0.5, 0.25] = 1.0
    human_assistance: HumanAssistance = Field(default_factory=HumanAssistance)


def effective_config(settings: RunSettings, controller=None) -> dict:
    config = settings.model_dump()
    name = settings.controller
    if name == "jev":
        config["model"] = controller._model
        config["policy"] = "direct-categorical"
        config["experimental"] = True
        config["assistance"] = "none"
    else:
        config["model"] = (
            getattr(controller, "model_id", settings.model) if name == "codex" else None
        )
    if name != "human":
        config["human_assistance"] = {"auto_center": False, "wing_leveler": False}
    if settings.mode == "lockstep":
        config["time_scale"] = 1.0
    return config


def now() -> str:
    return datetime.now(UTC).isoformat()


def new_run_id() -> str:
    return str(uuid4())


def source_identity() -> dict:
    versions = {}
    for package in ("flightbench", "jsbsim", "gymnasium"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = "source"
    digest = hashlib.sha256()
    for path in SOURCE_FILES:
        if path.is_file():
            digest.update(
                path.relative_to(ROOT).as_posix().encode()
                if path.is_relative_to(ROOT)
                else path.name.encode()
            )
            digest.update(path.read_bytes())
    return {"versions": versions, "source_hash": f"sha256:{digest.hexdigest()}"}


def _path(run_id: str, directory: Path) -> Path:
    canonical = str(UUID(run_id))
    if canonical != run_id:
        raise ValueError("run_id must be a canonical UUID")
    return directory / f"{canonical}.json"


def save_record(record: dict, directory: Path) -> Path:
    path = _path(record["run_id"], directory)
    directory.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(record, indent=2, allow_nan=False) + "\n"
    # Publish only a complete file; hard-link creation is atomic and never replaces a run.
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=directory, suffix=".tmp", delete=False
    ) as output:
        temporary = Path(output.name)
        try:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
            os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return path


def load_record(run_id: str, directory: Path) -> dict:
    return json.loads(_path(run_id, directory).read_text(encoding="utf-8"))


def summary(record: dict) -> dict:
    return {
        key: record[key]
        for key in (
            "schema_version",
            "run_id",
            "source",
            "started_at",
            "finished_at",
            "config",
            "source_identity",
            "outcome",
            "diagnostics",
        )
    }


def list_records(directory: Path) -> list[dict]:
    if not directory.exists():
        return []
    # ponytail: linear archive scan; add a small index only if local history outgrows it.
    records = []
    for path in directory.glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            records.append(summary(record))
        except (KeyError, TypeError, OSError, ValueError):
            continue
    return sorted(records, key=lambda row: row["finished_at"], reverse=True)
