"""Explicit local controller loading, not a plugin framework or a server endpoint."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
from pathlib import Path

from .core import ControlCommand
from .protocol import (
    SharedActionDecision,
    canonical_observation,
    command_from_action_ids,
    protocol_metadata,
)


class ExternalController:
    def __init__(self, reference: str) -> None:
        module_name, separator, class_name = reference.rpartition(":")
        if not separator or not module_name or not class_name.isidentifier():
            raise ValueError(
                "External controller must be module.path:ClassName or file.py:ClassName"
            )
        if module_name.endswith(".py"):
            path = Path(module_name).resolve(strict=True)
            spec = importlib.util.spec_from_file_location("flightbench_external", path)
            if spec is None or spec.loader is None:
                raise ValueError("Cannot load controller module")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        else:
            module = importlib.import_module(module_name)
            path = Path(module.__file__).resolve()
        self.controller = getattr(module, class_name)()
        if not callable(getattr(self.controller, "decide", None)):
            raise TypeError("External controller must implement decide(observation)")
        self.metadata = dict(getattr(self.controller, "metadata", {}))
        self.metadata.setdefault("name", class_name)
        self.metadata.setdefault("controller_type", "ai")
        if self.metadata["controller_type"] not in {"ai", "classical", "human", "reference"}:
            raise ValueError("Unknown controller_type")
        self.metadata["adapter_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.model_id = self.metadata.get("model", reference)

    def decide(self, observation):
        ai = self.metadata["controller_type"] == "ai"
        decision = self.controller.decide(canonical_observation(observation) if ai else observation)
        if ai:
            ids = SharedActionDecision.model_validate(decision)
            command = command_from_action_ids(ids)
            self.last_decision = {
                "controller": "external",
                **protocol_metadata(),
                "action_ids": ids.model_dump(),
                "command": command.model_dump(),
            }
        else:
            command = ControlCommand.model_validate(decision)
            self.last_decision = getattr(self.controller, "last_decision", None)
        return command
