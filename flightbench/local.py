"""Local Ollama transport for the frozen categorical protocol (stdlib only)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener

from pydantic import BaseModel

from .protocol import (
    SharedActionDecision,
    action_space,
    build_llm_control_prompt,
    canonical_observation,
    command_from_action_ids,
    protocol_metadata,
)


def _local_endpoint(endpoint: str) -> str:
    endpoint = endpoint.rstrip("/")
    url = urlparse(endpoint)
    if (
        url.scheme != "http"
        or url.hostname not in {"127.0.0.1", "localhost", "::1"}
        or url.username
        or url.password
        or url.path
        or url.query
        or url.fragment
    ):
        raise ValueError("Model endpoint must be a plain loopback HTTP URL")
    return endpoint


class OllamaController:
    def __init__(self, model: str | None = None, endpoint: str | None = None) -> None:
        if not model or model.endswith(":cloud"):
            raise ValueError("Specify an installed local Ollama model, not a cloud model")
        self.endpoint = _local_endpoint(
            endpoint or os.environ.get("FLIGHTBENCH_OLLAMA_URL", "http://127.0.0.1:11434")
        )
        self.model_id = model
        self._opener = build_opener(ProxyHandler({}))
        show = self._request("show", {"model": model})
        self._system_one = "decision" in show.get("capabilities", [])
        if show.get("remote_host") or show.get("remote_model"):
            raise ValueError("Cloud models are not local benchmark participants")
        tags = self._request("tags")
        installed = next((x for x in tags.get("models", []) if x["name"] == model), None)
        if installed is None:
            raise ValueError("Model must be installed locally before evaluation")
        self.metadata = {
            "name": model,
            "model": model,
            "provider": "Ollama local",
            "controller_type": "ai",
            "local": True,
            "model_digest": installed["digest"],
            "quantization": show.get("details", {}).get("quantization_level"),
            "parameter_count": show.get("model_info", {}).get("general.parameter_count"),
            "ollama_version": self._request("version")["version"],
            "endpoint": self.endpoint,
            "generation_options": {"temperature": 0, "seed": 0, "num_ctx": 8192, "num_predict": 96},
            "think": False,
            "transport": "systemone" if self._system_one else "chat",
            "cost_methodology": "Local provider fee is zero; hardware and electricity excluded.",
        }

    def _request(self, method: str, payload: dict | None = None) -> dict:
        request = Request(
            f"{self.endpoint}/v1/systemone"
            if method == "systemone"
            else f"{self.endpoint}/api/{method}",
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Content-Type": "application/json"},
        )
        with self._opener.open(request, timeout=120) as response:
            return json.load(response)

    def decide(self, observation):
        if isinstance(observation, BaseModel):
            observation = observation.model_dump(mode="json")
        state = canonical_observation(observation)
        if self._system_one:
            axes = action_space()["phases"][state["phase"]]
            questions = {
                axis: {
                    "type": "choice",
                    "instructions": spec["instructions"],
                    "criteria": {action["id"]: action["criterion"] for action in spec["actions"]},
                }
                for axis, spec in axes.items()
            }
            response = self._request(
                "systemone",
                {
                    "model": self.model_id,
                    "state": state,
                    "questions": questions,
                    "keep_alive": "10m",
                },
            )
            usage = response.get("usage") or {}
            # Von emits a nonempty truncation report only when input was dropped.
            if (
                response.get("truncated")
                or response.get("truncation")
                or usage.get("truncated")
                or (
                    usage.get("state_tokens_used") is not None
                    and usage.get("state_tokens") is not None
                    and usage["state_tokens_used"] < usage["state_tokens"]
                )
            ):
                raise ValueError("Local model truncated the canonical observation")
            answers = response["answers"]
            ids = SharedActionDecision.model_validate(
                {axis: value["choice"] for axis, value in answers.items()}
            )
            command = command_from_action_ids(ids)
            self.last_decision = {
                "controller": "systemone" if isinstance(self, SystemOneController) else "ollama",
                "model": self.model_id,
                **protocol_metadata(),
                "input": state,
                "choices": answers,
                "action_ids": ids.model_dump(),
                "command": command.model_dump(),
                "usage": response.get("usage"),
                "input_integrity": {key: response.get(key) for key in ("truncated", "truncation")},
                "sdk_request": {"questions": questions},
            }
            return command
        response = self._request(
            "chat",
            {
                "model": self.model_id,
                "messages": [
                    {"role": "system", "content": build_llm_control_prompt(state["phase"])},
                    {"role": "user", "content": json.dumps(state, separators=(",", ":"))},
                ],
                "format": SharedActionDecision.model_json_schema(),
                "stream": False,
                "think": False,
                "options": self.metadata["generation_options"],
                "keep_alive": "10m",
            },
        )
        if response.get("done") is not True or response.get("done_reason") == "length":
            raise ValueError("Local model returned a truncated decision")
        ids = SharedActionDecision.model_validate_json(response["message"]["content"])
        command = command_from_action_ids(ids)
        self.last_decision = {
            "controller": "ollama",
            "model": self.model_id,
            **protocol_metadata(),
            "input": state,
            "action_ids": ids.model_dump(),
            "command": command.model_dump(),
            "usage": {
                "input_tokens": response.get("prompt_eval_count"),
                "output_tokens": response.get("eval_count"),
            },
            "provider_timing_ns": {
                key: response.get(key)
                for key in (
                    "total_duration",
                    "load_duration",
                    "prompt_eval_duration",
                    "eval_duration",
                )
            },
        }
        return command


class SystemOneController(OllamaController):
    """The same choices over vetted local Kev/Von/Laya/Decider HTTP runtimes."""

    def __init__(self, model: str | None = None, endpoint: str | None = None) -> None:
        if not model:
            raise ValueError("Specify the locally served decision model")
        self.endpoint = _local_endpoint(
            endpoint or os.environ.get("FLIGHTBENCH_SYSTEMONE_URL", "http://127.0.0.1:11436")
        )
        self.model_id = model
        self._opener = build_opener(ProxyHandler({}))
        self._system_one = True
        metadata_path = os.environ.get("FLIGHTBENCH_LOCAL_METADATA")
        self.metadata = json.loads(Path(metadata_path).read_text()) if metadata_path else {}
        self.metadata.update(
            {
                "model": model,
                "controller_type": "ai",
                "local": True,
                "endpoint": self.endpoint,
                "transport": "systemone",
            }
        )
        self.metadata.setdefault("name", model)
        self.metadata.setdefault(
            "cost_methodology", "Local provider fee is zero; hardware and electricity excluded."
        )
